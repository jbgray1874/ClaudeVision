import csv
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from math import floor, pi as _PI
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import engine_build
import applied_finish
import source_precedence
from source_precedence import apply_field as _apply_field

import config
from config import (
    CSV_HEADERS,
    HOURLY_RATES_GBP,
    LABOUR_RULES,
    MATERIAL_DENSITY_KG_PER_M3,
    MATERIAL_PRICE_GBP_PER_KG,
    NESTING_RULES,
    STANDARD_SHEET_SIZES_MM,
    WORKBOOK_EQUIVALENT_PRICING,
)
from estimate_source_extract import build_estimate_source_extract
import costed_facts as _costed_facts
import price_provenance
from price_provenance import classify_price_source
import supplier_reference as _supplier_reference
from price_sources import PriceRequest, get_best_price
from unit_parsing import is_per_kg_unit, is_per_hour_unit

# Lazy PricingService singleton — the newer, token-scored pricing engine
# (UDEF + historical-quote RAG + supplier catalogue + LLM fallback). Used as a
# FALLBACK in _resolve_part_system_cost: the legacy price_sources connector
# (UDEF-only, no historical RAG) returns None for bought-in items like the loom,
# leaving them at the £0.42 handling floor. PricingService finds them
# (e.g. "50cm LOOM" -> £24.15 from historical_quote_material_line) so bought-in
# line items in the workbook are priced from the identified drawing items rather
# than the £0.42 floor or a static manual JSON.
_PRICING_SERVICE_SINGLETON = None
_PRICING_SERVICE_FAILED = False
_PRICING_SERVICE_ERROR = None      # why, when it could not be reached. See _get_pricing_service.

def _get_pricing_service():
    """Return a shared PricingService, or None if it can't be constructed
    (e.g. DB unavailable). Cached; never raises into the estimate path."""
    global _PRICING_SERVICE_SINGLETON, _PRICING_SERVICE_FAILED
    # SDI_OFFLINE MEANS OFFLINE, NOT "OFFLINE FOR learning_engine".
    #
    # The rules suite sets SDI_OFFLINE=1 before importing anything, and one module honoured
    # it. Everything costing reached straight past it: estimate_part -> estimate_material ->
    # _resolve_material_price -> PricingService -> SQL Server, and from there the xAI price
    # lookup. Two fixtures that call estimate_part therefore made live database and LLM
    # calls on any machine that could reach them -- fast where nothing is routable, minutes
    # or an indefinite block on the SDI network, where pyodbc.connect has no timeout.
    #
    # A suite that dials production is not isolated, cannot run in CI, and makes every
    # fixture depend on a server being up. That was already written down in
    # test_the_rules_suite_touches_no_live_service; the guard it checks simply did not cover
    # the path that spends money.
    #
    # Ordered after the singleton check on purpose: the guard exists to stop this process
    # CONSTRUCTING a connection, not to stop it using a service it was explicitly handed.
    # A fixture that injects a recording stub is testing what the caller passes, and must
    # still get its stub -- offline means "do not dial out", not "do not cost".
    if _PRICING_SERVICE_SINGLETON is not None:
        return _PRICING_SERVICE_SINGLETON
    if os.environ.get("SDI_OFFLINE"):
        return None
    if _PRICING_SERVICE_FAILED:
        return None
    try:
        from pricing_service import PricingService
        _PRICING_SERVICE_SINGLETON = PricingService()
        return _PRICING_SERVICE_SINGLETON
    except Exception as exc:
        # A JOB PRICED WITH NO PRICE SOURCE MUST NOT LOOK LIKE A CHEAP JOB.
        #
        # PricingService connects in __init__, so an unreachable SDILive -- a dropped VPN,
        # a stopped service, a rotated login -- raises here. This said NOTHING, set a flag,
        # and returned None; every caller then took the None branch and costed from
        # fallbacks. The run completed, the workbook calculated, the reports were written
        # and the unit price came out LOW, with no line anywhere on the console, in the
        # sheet or in the invariants saying that the primary price source had never been
        # reached. That estimate is indistinguishable from a correct one and it is the
        # single most expensive thing this engine could do quietly.
        #
        # Two changes: say it once, with the reason; and RECORD it, so the fact survives to
        # the reports and the checks rather than living in scrollback the runner discards.
        global _PRICING_SERVICE_ERROR
        _PRICING_SERVICE_FAILED = True
        _PRICING_SERVICE_ERROR = f"{type(exc).__name__}: {exc}"
        print(f"\n   *** UDEF/SDILive COULD NOT BE REACHED — {_PRICING_SERVICE_ERROR}\n"
              f"   *** Every catalogue and history price on this job is MISSING, not zero.\n"
              f"   *** The unit cost below is costed from fallbacks only. DO NOT SEND IT "
              f"TO ESTIMATING.", flush=True)
        return None


def pricing_source_failure() -> Optional[str]:
    """Why the price source could not be reached, or None if it was.

    Read by file_scan so the job record carries it, and by the invariants so a job priced
    with no price source fails a check instead of merely having failed quietly.
    """
    return _PRICING_SERVICE_ERROR


def stamp_price_source_status(summary: Dict[str, Any], json_path: Any = None) -> Optional[str]:
    """Record on the job whether the price source was ever reached. Returns the reason, or None.

    BOTH THE SUMMARY AND THE SAVED JSON, deliberately. The invariants prefer the stamped
    document on disk -- it is the one with final_estimate on it -- and fall back to the
    in-memory summary when the JSON cannot be read. Stamping only one leaves the other
    reporting a clean job, and two views of one estimate that disagree is the exact defect
    that layer exists to stop.

    A function rather than a block inside main so it can be exercised. The first version was
    inline and the only test that could reach it grepped main.py for a string, which is not
    a test: deleting the summary stamp left the string in place on the JSON line and the
    grep stayed green.
    """
    why = pricing_source_failure()
    if not why:
        return None
    summary["price_source_unreachable"] = why
    if json_path:
        from pathlib import Path as _P
        p = _P(str(json_path))
        if p.exists():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                doc["price_source_unreachable"] = why
                p.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
            except Exception as exc:
                # SAY IT, do not raise. Losing the estimate because the outage could not be
                # written down would be a worse outcome than the outage; but a silent failure
                # here puts the job back to looking clean, so it has to be spoken.
                print(f"   [pricing] the price-source outage could not be written to the JSON "
                      f"({type(exc).__name__}: {exc}) — the in-memory summary carries it and "
                      f"the console line above is the other record.", flush=True)
    return why


def record_operation(part: Dict[str, Any], op: str, source: str,
                     *, inferred: bool = True) -> None:
    """The only way this module puts an operation onto a part.

    STEP 0 OF THE ROUTE CUTOVER, and the reason it comes first.
    operation_sources was written in exactly one place -- the LLM route fold -- so every
    operation the deterministic reader, SolidWorks, or the estimator itself concluded
    carried NO source at all. rank("") is 0, and llm_full_extract is 40, so any arbitration
    over those claims would silently hand every contested operation to the model.

    12120's own shadow proves the scale: thirteen handling decisions, tapping, and one
    welding all came out as `unknown 0`. That is a third of the route with no provenance,
    and it has to be fixed BEFORE ranked arbitration decides anything, or the compiler will
    look wrong when the data underneath it is what is missing.

    This changes no number today. Nothing reads operation_sources for costing; it is read by
    the route compiler in shadow, and by the arbitration that follows at cutover.
    """
    _o = str(op or "").strip().lower()
    if not _o:
        return
    _key = "inferred_operations" if inferred else "textual_operations"
    _ops = part.setdefault(_key, [])
    if isinstance(_ops, list) and _o not in _ops:
        _ops.append(_o)
    # RANK, NOT ARRIVAL ORDER.
    #
    # setdefault protected a strong existing attribution from a weak new one -- and equally
    # blocked a MEASUREMENT from upgrading an earlier guess, which is the same defect in the
    # other direction. Whoever writes first should not win by writing first.
    try:
        from source_precedence import rank as _rank
    except Exception:                                   # pragma: no cover - import guard
        _rank = lambda _s: 0                            # noqa: E731
    _srcs = part.setdefault("operation_sources", {})
    _existing = _srcs.get(_o)
    if not _existing or _rank(source) > _rank(_existing):
        _srcs[_o] = source


def _first(values: List[Any]) -> Any:
    return values[0] if values else None


def _join(values: List[Any]) -> str:
    return "; ".join(str(value) for value in values if value not in (None, ""))


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_stated_weight_kg(part: Dict[str, Any]) -> Optional[float]:
    """Extract a stated weight from the part's extracted 'weights' field (e.g. '885g', '1.2KG').
    Also checks stated_weight_g field written by file_scan weight extraction."""
    # Direct stated_weight_g field (written by improved weight regex in file_scan.py)
    _swg = _safe_float(part.get("stated_weight_g"))
    if _swg is not None and _swg > 0:
        _kg = _swg / 1000.0
        if 0.001 <= _kg <= 500.0:
            return round(_kg, 4)
    # The part's own BOM-row weight, stamped by apply_bom_row_evidence_to_parts at
    # bom_tree rank. 0359342: MBY432 is 90g of bent wire and MBY434 a 10g plate — the
    # printed weights sat on the records while the per-each fallback priced them at
    # £699 and £3,203 for about £4 of steel between them. MBY439, whose weight arrived
    # through the older field, priced sanely on this same path all along.
    _swkg = _safe_float(part.get("stated_weight_kg"))
    if _swkg is not None and 0.001 <= _swkg <= 500.0:
        return round(_swkg, 4)
    weights = part.get("weights") or part.get("title_block", {}).get("weights") or []
    if isinstance(weights, str):
        weights = [weights]
    for w in weights:
        text = str(w).strip().upper().replace(",", "")
        m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(KG|G)$", text)
        if not m:
            continue
        val = float(m.group(1))
        if m.group(2) == "G":
            val = val / 1000.0
        if 0.001 <= val <= 500.0:
            return round(val, 4)
    return None


def _stated_weight_kg_for_part(part: Dict[str, Any]) -> Optional[float]:
    """Prefer DXF flat-pattern mass; fall back to title-block WEIGHT (e.g. 138.85g)."""
    dxf_g = _safe_float(part.get("dxf_weight_g"))
    if dxf_g is not None and dxf_g > 0:
        return round(dxf_g / 1000.0, 4)
    dxf_kg = _safe_float(part.get("dxf_weight_kg"))
    if dxf_kg is not None and dxf_kg > 0:
        return round(dxf_kg, 4)
    return _parse_stated_weight_kg(part)


def _price_per_kg_for_material(part: Optional[Dict[str, Any]], material) -> Optional[float]:
    """The GBP/kg for this material, including when the rate table is not keyed by its name.

    0359342's BOM writes its materials as the drawing office types them — "CR4, 2mm",
    "Steel, Mild Wire", "MildSteel", "Steel,Mild2mm". All four are mild steel and this engine
    holds a mild-steel rate, but a plain dict lookup on those strings returns None, and a None
    here does not read as "no rate for mild steel" — it silently skips the whole stated-weight
    costing path. A 10 g prong backplate that its own BOM row weighed then fell through to a
    generated market figure of GBP 55 each: GBP 3,203 for 56 of them.

    A name that the table already holds is answered directly and never resolved, so nothing
    that prices today can move through this function. Only a name with no rate of its own is
    reduced to its material words (config.resolve_material_rate_key), and when that lands on a
    real rate the substitution is RECORDED on the part — a line costed as MILD STEEL when the
    drawing said "Steel, Mild Wire" has been read, not quoted, and the estimator is told so.
    """
    direct = MATERIAL_PRICE_GBP_PER_KG.get(material or "")
    if direct is not None:
        return direct
    # A PURCHASED SCREW IS NOT PRICED BY ITS SCRAP WEIGHT, AND THIS IS WHERE I BROKE THAT.
    #
    # Resolving "MildSteel" to MILD STEEL gave the fasteners a GBP/kg rate they never had, and
    # the stated-weight path then costed them by mass: 0359342's M6 button-head screw and M8
    # T-nut both came out at GBP 0.01 EACH. That is as wrong as the GBP 7.50 it replaced, in the
    # direction nobody notices — the exact trade this work is supposed to avoid. A fastener's
    # price is its CATALOGUE price; the steel in it is a rounding error against the thread, the
    # plating and the box.
    #
    # So a part the shared bought-in vocabulary recognises as purchased hardware is refused a
    # resolved per-kg rate, and falls back to the indicative/unpriced treatment it had before —
    # an honest gap that the bought-in price book (backlog #11) is the real answer to. Only the
    # RESOLVED path is gated: a name that already carried a rate behaves exactly as it did, so
    # this neither widens nor narrows anything outside the change that caused it.
    if isinstance(part, dict):
        try:
            from pack_profile import BOUGHT_IN, family_for
            from part_identity import synthesise_bought_in_code
            _pn = str(part.get("part_number") or "")
            _desc = str(part.get("description") or "")
            if synthesise_bought_in_code(_desc) or family_for("", _pn, "") == BOUGHT_IN:
                return None
        except Exception:                                    # noqa: BLE001
            pass
    try:
        import config as _cfg
        key = _cfg.resolve_material_rate_key(material)
    except Exception:                                        # noqa: BLE001
        return None
    if not key or key == material:
        return None
    rate = MATERIAL_PRICE_GBP_PER_KG.get(key)
    if rate is None:
        return None
    # RESOLVING A NAME MUST NOT RE-ROUTE A PART TO A DIFFERENT COSTING BASIS.
    #
    # The sheet-priced plastics carry a GBP/kg entry as well as their area rate, and the area
    # rate is the one this engine costs them on. "2mm ACRYLIC" has no rate under that exact
    # name, so resolving it to ACRYLIC would hand the per-kg path a rate it never had — and a
    # 400x300x18mm acrylic panel priced by mass comes out at GBP 57.49 where the area path
    # says a few pounds. That is not this fix's job and it is not this fix's evidence: the
    # gauge-prefixed plastics were unpriced before and stay unpriced, visibly, until someone
    # routes them to the area path deliberately.
    #
    # Steel, timber and board are untouched by this gate — they are mass-priced already, which
    # is exactly why the stated-weight path is the right home for a part that states a weight.
    try:
        import config as _cfg2
        if str(key).strip().upper() in getattr(_cfg2, "PLASTIC_SHEET_PRICED_MATERIALS", frozenset()):
            return None
    except Exception:                                        # noqa: BLE001
        return None
    if isinstance(part, dict):
        part["material_rate_key_resolved"] = {"recorded": material, "priced_under": key}
        _flag = (f"material recorded as '{material}' carries no rate under that name; priced "
                 f"under '{key}', which is the same material with the gauge and stock form "
                 f"taken out of the cell. Confirm the grade if it matters to the rate.")
        if _flag not in (part.get("review_flags") or []):
            part.setdefault("review_flags", []).append(_flag)
    return rate


def _weight_source_label(part: Dict[str, Any]) -> str:
    if part.get("dxf_weight_g") or part.get("dxf_weight_kg"):
        return "dxf_flat_pattern"
    if part.get("geometry_source") == "dxf_flat_pattern" or part.get("dxf_augmented"):
        return "dxf_flat_pattern"
    if str(part.get("geometry_source") or "") == "solidworks_flat_pattern":
        return "solidworks_flat_pattern"
    return "pdf_stated"


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_price_source_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _rounding_mode() -> str:
    policy = getattr(config, "ROUNDING_POLICY", {}) or {}
    return str(policy.get("mode", "final_total_only")).strip().lower()


def _estimate_policy_snapshot_for_manifest() -> Dict[str, Any]:
    """Stable snapshot hashed into estimate_policy_manifest.policy_fingerprint_sha256."""
    wb = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    section = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
    return {
        "estimate_policy_version": getattr(config, "ESTIMATE_POLICY_VERSION", "unknown"),
        "scrap_fraction": getattr(config, "SCRAP_PERCENTAGE", 0),
        "output_manufacturing_cost_only": bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)),
        "assumed_job_quantity": wb.get("default_job_quantity"),
        "scrap_pct_workbook": wb.get("scrap_pct"),
        "powder_costing_policy": dict(getattr(config, "POWDER_COSTING_POLICY", {}) or {}),
        "labour_rule_powder_coating": dict((getattr(config, "LABOUR_RULES", {}) or {}).get("powder_coating", {}) or {}),
        "hourly_rate_powder_coating_gbp": float(HOURLY_RATES_GBP.get("powder_coating", 0.0) or 0.0),
        "rounding_policy": dict(getattr(config, "ROUNDING_POLICY", {}) or {}),
        "section_stock_waste_factor_pct": section.get("waste_factor_pct"),
    }


def _estimate_policy_fingerprint_sha256(snapshot: Dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_estimate_policy_manifest() -> Dict[str, Any]:
    snap = _estimate_policy_snapshot_for_manifest()
    return {
        "schema": "estimate_policy_manifest.v1",
        "policy_fingerprint_sha256": _estimate_policy_fingerprint_sha256(snap),
        "policy_snapshot": snap,
        "calibration_notes": [
            "Powder throughput: divide actual booth hours into known coated area from one closed job "
            "to fit LABOUR_RULES['powder_coating']['throughput_m2_per_hour'].",
            "Powder £/kg: use POWDER_MATERIAL_GBP_PER_KG and POWDER_MATERIAL_SPECIAL_GBP_PER_KG for standard vs metallics/textures.",
        ],
    }


def _build_estimate_review_signals(part_estimates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rolls up heuristic risk_flags and quantitative gates so dashboards can queue human review early.
    """
    conf_thr = float(os.getenv("ESTIMATE_PART_CONFIDENCE_REVIEW_BELOW", "0.65") or "0.65")
    geom_thr = float(os.getenv("ESTIMATE_GEOMETRY_REVIEW_BELOW", "0.70") or "0.70")
    parts_out: List[Dict[str, Any]] = []
    for p in part_estimates:
        reasons: List[Dict[str, Any]] = []
        for rf in p.get("risk_flags") or []:
            reasons.append({"code": "risk_flag", "detail": str(rf)})
        assump = (p.get("cost_breakdown") or {}).get("assumptions") or {}
        pc_val = _safe_float(assump.get("part_confidence_overall"))
        if pc_val is not None and pc_val < conf_thr:
            reasons.append({"code": "low_part_confidence", "detail": pc_val})
        proc = p.get("process_estimate") or {}
        gr = _safe_float(proc.get("geometry_reliability"))
        times_min = proc.get("times_min") or {}
        if "powder_coating" in times_min and gr is not None and gr < geom_thr:
            reasons.append({"code": "low_geometry_reliability_with_powder", "detail": gr})
        if reasons:
            # Carry a FALLBACK IDENTITY, not just the part_number. A part whose number was
            # rejected as boilerplate (set to None upstream) still has a description and a source
            # file — without them the review report can only show "?" in its Item column, a flag
            # the estimator cannot tie to anything. Same nameless-part gap the blocking flags fixed.
            parts_out.append({"part_number": p.get("part_number"),
                              "description": p.get("description"),
                              "source_file": p.get("dxf_source_file") or p.get("source_file"),
                              "reasons": reasons})
    rec = "manual_review_recommended" if parts_out else "no_automatic_flags"
    return {
        "schema": "estimate_review_signals.v1",
        "thresholds": {"part_confidence_below": conf_thr, "geometry_with_powder_below": geom_thr},
        "parts_flagged": parts_out,
        "flagged_part_count": len(parts_out),
        "recommendation": rec,
    }


def _mfg_lookup(parts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map part_number (and description fallback) to manufacturing writeup part."""
    by_pn: Dict[str, Dict[str, Any]] = {}
    by_desc: Dict[str, Dict[str, Any]] = {}
    for p in parts:
        pn = str(p.get("part_number") or "").strip()
        if pn and pn.upper() not in ("NONE", "?"):
            by_pn[pn.upper()] = p
        dsc = str(p.get("description") or "").strip().upper()
        if dsc:
            by_desc[dsc] = p
    out = dict(by_pn)
    out.update({f"__DESC__{k}": v for k, v in by_desc.items()})
    return out


def _resolve_mfg_part(mfg_by_key: Dict[str, Dict[str, Any]], est_part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pn = str(est_part.get("part_number") or "").strip().upper()
    if pn and pn not in ("NONE", "?"):
        hit = mfg_by_key.get(pn)
        if hit:
            return hit
    dsc = str(est_part.get("description") or "").strip().upper()
    if dsc:
        return mfg_by_key.get(f"__DESC__{dsc}")
    return None


def _has_native_flat(part: Dict[str, Any]) -> bool:
    """True when the blank came from the SolidWorks sheet-metal CUT LIST — a modelled flat
    pattern, i.e. the same measured truth as a DXF flat (it is what generates the DXF), and
    sanity-gated against the solid before it is written. Kept as a separate predicate from
    the DXF ones so nothing anywhere claims a DXF exists when it does not; every gate that
    means "this part has measured geometry" ORs the two together."""
    if not isinstance(part, dict):
        return False
    return bool(part.get("native_flat_pattern")) or (
        str(part.get("geometry_source") or "").lower() == "solidworks_flat_pattern"
    )


def _part_has_part_dxf(mfg: Dict[str, Any]) -> bool:
    # A modelled flat pattern is measured geometry of the same class as a DXF flat, so the
    # credibility gate must accept it — otherwise a fully native job (better data than any
    # DXF job) would be stamped "insufficient data" for lacking a file it does not need.
    if _has_native_flat(mfg):
        return True
    if mfg.get("dxf_augmented"):
        return True
    gs = str(mfg.get("geometry_source") or "").lower()
    return "dxf" in gs


def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (credible, reasons) for whether this part's cost belongs in the headline total."""
    reasons: List[str] = []
    ext = float(est_part.get("extended_total_cost_gbp") or 0.0)
    if ext <= 0:
        return True, []

    mfg = mfg or {}

    # Bought-in parts structurally never have a DXF -- that's not a credibility
    # problem, it's the nature of the part. Exempt them from no_part_dxf so a
    # well-priced catalogue/historical line doesn't drag the cost-credibility
    # ratio down for lacking geometry it was never going to have. page_roles
    # is the signal confirmed 100%-reliable against real job data (1282,
    # all 15 bought-in parts) -- see credibility gate probe.
    if "bought_in" in [str(r).lower() for r in (mfg.get("page_roles") or [])]:
        return True, []

    # A LINEAR-STOCK PART (WIRE / BAR / TUBE / SECTION) IS NOT A FLAT, SO THE FLAT-PATTERN
    # DOUBTS DO NOT APPLY.
    #
    # A wire, bar, tube or section is costed from a section rate and its gauge/profile, not from
    # a blank read off a DXF or inflated off a PDF view — so no_part_dxf and pdf_geometry_inflation
    # are the wrong doubts for it, exactly as they are for a bought-in that never has a flat
    # pattern. Left in, they put the part's whole extended cost (mostly forming/weld/bend LABOUR,
    # which no geometry reading touches) into the "doubted" column: on 11762-17 the wires read as
    # "5% of this job is trustworthy", and on 7332-01 the tube LEG (£24.08, no flat DXF because a
    # tube has none) dragged the ratio to 28%. This is the same family the route compiler already
    # treats as one — ("tube","wire","section","bar"). Where a developed length was assumed, that
    # caveat still travels on the part's own INDICATIVE review flag, so nothing flagged stops being
    # flagged.
    _LINEAR_STOCK = {"wire", "bar", "tube", "section", "profile", "extrusion", "rod"}
    _me_cred = est_part.get("material_estimate") or {}
    _mi_cred = (est_part.get("manufacturing_interpretation")
                or mfg.get("manufacturing_interpretation") or {})
    _cm_cred = str(_me_cred.get("cost_method") or est_part.get("cost_method") or "").lower()
    _ss_cred = est_part.get("section_stock") or mfg.get("section_stock") or {}
    _is_linear_stock = (
        str(_me_cred.get("stock_form") or "").lower() in _LINEAR_STOCK
        or str(_mi_cred.get("stock_form") or "").lower() in _LINEAR_STOCK
        or bool(est_part.get("_bar_recognised"))
        or bool(_ss_cred.get("a") and _ss_cred.get("b") and _ss_cred.get("t"))
        or bool(_ss_cred.get("length_mm"))
        or _cm_cred.startswith("wire_") or "bar_formula" in _cm_cred
        or "section" in _cm_cred or "tube" in _cm_cred
    )
    if _is_linear_stock:
        return True, []

    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))

    if mfg.get("geometry_inferred"):
        reasons.append("geometry_inferred_provisional")
    if "implausible_system_cost_rejected" in rf_blob:
        reasons.append("rejected_catalogue_match")
    # SolidWorks named the material but the model yielded no blank/mass/section, so the
    # material cost is not derivable. Never let that line pass as a credible £0.
    if mfg.get("native_material_without_geometry"):
        reasons.append("native_material_no_geometry")

    has_dxf = _part_has_part_dxf(mfg)
    gr = _safe_float((est_part.get("process_estimate") or {}).get("geometry_reliability"))
    if gr is None:
        gr = _safe_float(((mfg.get("geometry_rollup") or {}).get("confidence") or {}).get("geometry_reliability"))

    if not has_dxf:
        reasons.append("no_part_dxf")
        cut = float((mfg.get("geometry_rollup") or {}).get("estimated_cut_length_mm") or 0)
        if cut > 3000 and (gr or 0) < 1.0:
            reasons.append("pdf_geometry_inflation_suspected")

    return (len(reasons) == 0), reasons


def _assess_estimate_data_sufficiency(
    source_parts: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
    document_total: float,
) -> Dict[str, Any]:
    """
    Say how much of this total rests on a measurement, and which lines do not.

    IT USED TO REFUSE TO REPORT THE NUMBER. A job where most of the money came from geometry
    read off a view was stamped INSUFFICIENT DATA and its headline was nulled — which reads,
    to anyone holding the same drawings, as the engine declining a job an estimator does by
    hand every day. It is also the wrong answer: those drawings DO support a price, and most
    of the lines on them are as solid as any other job's. James: "if the estimators can price
    off them, then the question will be asked why can't we. this sounds like a lame excuse."

    So it prices, and it says which lines are thin and why. Same arithmetic, same thresholds,
    same list of doubted parts — the difference is that the total is reported and the doubt
    travels beside it as a fact an estimator can act on, rather than as a verdict that leaves
    them with nothing. `provisional` carries the judgement now; the invariant that insists a
    weak number reaches the reader marked and reasoned reads that instead, so nothing that
    was guarded has stopped being guarded.
    """
    min_cost_ratio = float(getattr(config, "DATA_SUFFICIENCY_MIN_CREDIBLE_COST_RATIO", 0.50) or 0.50)
    min_dxf_ratio = float(getattr(config, "DATA_SUFFICIENCY_MIN_DXF_PART_RATIO", 0.25) or 0.25)

    mfg_by_key = _mfg_lookup(source_parts)
    credible_cost = 0.0
    unreliable_cost = 0.0
    unreliable_parts: List[Dict[str, Any]] = []

    for est in part_estimates:
        ext = float(est.get("extended_total_cost_gbp") or 0.0)
        mfg = _resolve_mfg_part(mfg_by_key, est)
        ok, reasons = _part_cost_credibility(mfg, est)
        if ext > 0 and not ok:
            unreliable_cost += ext
            unreliable_parts.append({
                "part_number": est.get("part_number"),
                "description": est.get("description"),
                "extended_cost_gbp": round(ext, 2),
                "reasons": reasons,
            })
        elif ext > 0:
            credible_cost += ext

    fabricated = [
        p for p in source_parts
        if str(p.get("normalized_material") or "").upper()
        not in {"BOUGHT_IN", "PAPER", "PRINTED_PAPER", "UNKNOWN", ""}
        and str(p.get("part_number") or "").upper() not in ("", "NONE", "?")
    ]
    with_dxf = [p for p in fabricated if _part_has_part_dxf(p)]
    dxf_part_ratio = len(with_dxf) / max(len(fabricated), 1)
    credible_cost_ratio = credible_cost / max(document_total, 0.01) if document_total > 0 else 1.0

    insufficient = False
    if document_total > 0 and credible_cost_ratio < min_cost_ratio:
        insufficient = True
    elif len(fabricated) >= 2 and dxf_part_ratio < min_dxf_ratio:
        insufficient = True

    _sized_from_drawing = max(len(fabricated) - len(with_dxf), 0)
    status = "provisional" if insufficient else "ok"
    msg = (
        (f"PROVISIONAL — {_sized_from_drawing} of {len(fabricated)} fabricated part(s) were "
         f"sized from the drawing rather than measured")
        if insufficient else "Data sufficiency OK"
    )
    reason = (
        (f"{credible_cost_ratio:.0%} of £{document_total:,.2f} rests on a measurement; the "
         f"rest on geometry read off a view or on prices that could not be verified. A part "
         f"DXF or a SOLIDWORKS model for the {_sized_from_drawing} part(s) below would move "
         f"those lines from read to measured.")
        if insufficient else ""
    )

    if insufficient:
        print(
            f"   [data] {msg} — {credible_cost_ratio:.0%} of £{document_total:,.2f} measured; "
            f"DXF on {dxf_part_ratio:.0%} of {len(fabricated)} fabricated part(s). Priced in "
            f"full and marked provisional.",
            flush=True,
        )

    # ── AND SEPARATELY: IS IT RELEASABLE ──────────────────────────────────────────────
    #
    # Two different questions, and conflating them is what let a normal-looking unit price
    # ship with four required costs missing from it. THIS function asks how much of the
    # total rests on a measurement — it is about CONFIDENCE, and its honest answer can be
    # "priced, and thin in these places". The release gate asks whether every required line
    # has an answer at all — it is about COMPLETENESS, and its only honest answers are yes
    # and no.
    #
    # A thin estimate is publishable with its doubts named. An incomplete one is not
    # publishable at any confidence, because the number it shows is not the price of the
    # thing. James: "It must never show a normal-looking £108.89 unit price that quietly
    # excludes four required costs."
    _release: Dict[str, Any] = {}
    try:
        from release_gate import assess_release
        _release = assess_release(
            [
                {
                    "code": _pe.get("part_number"),
                    "description": _pe.get("description"),
                    "price_gbp": ((_pe.get("material_estimate") or {})
                                  .get("applied_unit_price_gbp")
                                  or (_pe.get("cost_breakdown") or {}).get("material")),
                    "required": not bool(_pe.get("_not_required")),
                    "zero_reason": _pe.get("zero_reason"),
                    "rung": ((_pe.get("material_estimate") or {}).get("price_source")
                             or {}).get("source_type"),
                    "evidence": ((_pe.get("material_estimate") or {}).get("price_source")
                                 or {}).get("evidence"),
                    "owner": _pe.get("price_owner"),
                }
                for _pe in (part_estimates or []) if isinstance(_pe, dict)
            ]
        )
    except Exception as _e:                                          # noqa: BLE001
        # A gate that cannot run must not silently pass the job. Saying so is the answer.
        _release = {"schema": "estimate_release_gate.v1", "releasable": False,
                    "blocking": [], "lines_blocking": 0,
                    "headline": f"NOT RELEASABLE — the release gate could not run ({_e}). "
                                f"An estimate nobody checked is not an estimate that passed."}

    return {
        "schema": "estimate_data_sufficiency.v1",
        "status": status,
        "message": msg,
        # Carried here so every reader of the sufficiency block — workbook, report, quote —
        # reaches the same verdict without each one re-deriving it.
        "release": _release,
        "releasable": bool(_release.get("releasable")),
        # NOT SUPPRESSED ANY MORE, AND STILL DECLARED. The invariant that insists a weak
        # number reaches the reader marked and reasoned accepts `provisional` in place of the
        # suppression, so removing the blank total costs nothing that was protecting anybody.
        "suppress_headline_total": False,
        "provisional": insufficient,
        "provisional_reason": reason,
        "parts_sized_from_drawing": _sized_from_drawing,
        "document_total_provisional_gbp": round(document_total, 2),
        "document_total_reportable_gbp": round(document_total, 2),
        "credible_cost_gbp": round(credible_cost, 2),
        "unreliable_cost_gbp": round(unreliable_cost, 2),
        "credible_cost_ratio": round(credible_cost_ratio, 4),
        "fabricated_part_count": len(fabricated),
        "parts_with_dxf": len(with_dxf),
        "dxf_part_ratio": round(dxf_part_ratio, 4),
        "thresholds": {
            "min_credible_cost_ratio": min_cost_ratio,
            "min_dxf_part_ratio": min_dxf_ratio,
        },
        "unreliable_parts": unreliable_parts,
    }


def _money_decimals() -> int:
    policy = getattr(config, "ROUNDING_POLICY", {}) or {}
    return int(policy.get("money_decimals", 2))


def _round_money(value: Any) -> float:
    numeric = _safe_float(value) or 0.0
    return round(numeric, _money_decimals())


def _part_powder_material_extended_gbp(part_estimate: Dict[str, Any]) -> float:
    pc = (part_estimate.get("material_estimate") or {}).get("powder_consumable")
    if not isinstance(pc, dict):
        return 0.0
    return float(pc.get("extended_powder_material_cost_gbp") or 0.0)


def _part_powder_labour_gbp(part_estimate: Dict[str, Any]) -> float:
    costs = (part_estimate.get("labour_estimate") or {}).get("costs_gbp") or {}
    return float(costs.get("powder_coating") or 0.0)


def _extract_selected_price(result: Dict[str, Any]) -> Dict[str, Any]:
    selected = result.get("selected") or {}
    return selected if isinstance(selected, dict) else {}


def _selected_price_value(selected: Dict[str, Any]) -> Optional[float]:
    try:
        price = selected.get("price")
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def _selected_price_unit(selected: Dict[str, Any]) -> str:
    return str(selected.get("unit") or "").strip().lower()


def _build_price_source_metadata(
    result: Dict[str, Any],
    fallback_source: str,
    applied: bool,
    applied_basis: str | None = None,
    affects_total: bool | None = None,
) -> Dict[str, Any]:
    selected = _extract_selected_price(result)
    evidence = selected.get("evidence", {}) if isinstance(selected.get("evidence"), dict) else {}
    metadata = selected.get("metadata", {}) if isinstance(selected.get("metadata"), dict) else {}
    evidence_row = evidence.get("row", {}) if isinstance(evidence.get("row"), dict) else {}
    supplier_source = (
        metadata.get("supplier_name")
        or metadata.get("supplier_source")
        or evidence.get("supplier_name")
        or evidence.get("supplier_source")
        or evidence_row.get("supplier_name")
        or evidence_row.get("supplier_source")
        or selected.get("source")
        or fallback_source
    )
    source_name = selected.get("source") or fallback_source
    source_rank = (config.PRICE_FRESHNESS_RULES or {}).get("source_priority", {}).get(str(source_name), 0)
    freshness_bucket = _price_freshness_bucket(metadata.get("price_date") or evidence.get("price_date") or evidence_row.get("price_date"))
    freshness_penalty = (config.PRICE_FRESHNESS_RULES or {}).get("freshness_penalty", {}).get(freshness_bucket, 20.0)

    src_type = "external" if selected.get("source") else "config"
    if evidence.get("pricing_mode") == "web_ai_llm_estimate" or metadata.get("pricing_mode") == "web_ai_llm_estimate":
        src_type = "web_ai_fallback"
    elif str(source_name).lower() == "web" and selected.get("source"):
        src_type = "web_catalog"

    # WHERE A GUESSED PRICE USED TO HIDE. `src_type` above is derived from the *connector*
    # that answered, so anything reached through the pricing-service chain — including an LLM
    # market estimate — landed here as "external", the same word a SQL catalogue row carries.
    # Nothing downstream could tell the two apart, and three AI-priced bought-ins on 12120
    # passed the reproducibility check because of it. Classify by the source's identity, in
    # one shared place, so every writer and every checker reaches the same verdict.
    _pricing_mode = (evidence.get("pricing_mode") or metadata.get("pricing_mode")
                     or selected.get("pricing_mode"))
    _source_class = classify_price_source(
        source_name, source_type=src_type, pricing_mode=_pricing_mode,
        # `selected` IS ONLY FILLED BY AN EXTERNAL LOOKUP. Reading it alone meant every
        # INTERNALLY computed price -- the acrylic area rate, the workbook sheet-steel
        # formula, config's GBP/kg fallback -- was classified "unpriced" while its money sat
        # in the total. price_firmness then explained a real, applied figure as "a unpriced
        # price carries no commitment", which is true of nothing on that line, and the
        # documented "config" class was unreachable for the writers that produce it.
        #
        # The caller already states the fact: `applied` means a price was applied. Third
        # instance today of one field being asked a question it does not answer -- after
        # stamp_affects_total falling back to `applied`, and _UNPRICED_SOURCES holding "".
        priced=selected.get("price") is not None or bool(applied),
    )
    if _source_class == "ai_estimate" and src_type == "external":
        src_type = "web_ai_fallback"      # never let a generated price read as a catalogue hit

    return {
        # The marker consumers find priced lines by. Nothing downstream should have to know
        # WHERE in a part a price is stored — a block added to a new part shape is then
        # checked without the checker being taught about it.
        "schema": price_provenance.PRICE_SOURCE_SCHEMA,
        "source_class": _source_class,
        "reproducible": _source_class != "ai_estimate",
        "pricing_mode": _pricing_mode,
        # WHAT KIND OF PRICE, AND MAY WE STAND BEHIND IT. Two different questions: a public
        # list price repeats perfectly and is still not a quote we have committed to. The
        # validity fields are carried through from whatever supplied them and are absent on
        # every source today, which is itself the finding.
        "price_class": price_provenance.source_class_of(
            source_name, source_type=src_type, pricing_mode=_pricing_mode,
            priced=selected.get("price") is not None),
        "price_valid_to": (metadata.get("price_valid_to") or evidence.get("price_valid_to")
                           or metadata.get("valid_to")),
        "price_effective_at": (metadata.get("price_effective_at")
                               or metadata.get("price_date") or evidence.get("price_date")),
        "quote_reference": (metadata.get("quote_reference") or metadata.get("contract_id")
                            or evidence.get("quote_reference")),
        # Named, not just classified — "an AI estimate" is a category, "xAI Grok" is an answer
        # to the question an estimator actually asks about a number they cannot reproduce.
        "llm_provider": metadata.get("llm_provider") or evidence.get("llm_provider"),
        # `applied` means a price was found for this line. `affects_total` is narrower: a
        # bought-in unit cost can be resolved and then not added, because the part was costed
        # as a fabrication instead. Only money that reached the total can move the total.
        "affects_total": bool(applied if affects_total is None else affects_total),
        # The resolver's own account of which sources answered and whether they agreed. A
        # price that moves between runs is otherwise invisible: every run is internally
        # consistent and the number is simply different.
        "provenance": result.get("provenance"),
        "review_reason": (
            selected.get("review_reason")
            or metadata.get("review_reason")
            or price_provenance.review_reason_for(_source_class, source_name)
        ),
        "supplier_source": supplier_source,
        "supplier_code": metadata.get("supplier_code") or evidence.get("supplier_code") or evidence_row.get("supplier_code"),
        "price_date": metadata.get("price_date") or evidence.get("price_date") or str(date.today()),
        "source_type": src_type,
        "source_name": source_name,
        "source_rank": source_rank,
        "unit": selected.get("unit") or "unknown",
        "currency": selected.get("currency") or "GBP",
        "confidence": selected.get("confidence"),
        "applied": applied,
        "applied_basis": applied_basis,
        "freshness_bucket": freshness_bucket,
        "freshness_penalty": freshness_penalty,
        "source_note": evidence.get("source_note") or metadata.get("source_note"),
        "web_query": evidence.get("web_query"),
        "selected": selected,
        "audit_trail": result.get("audit_trail", []),
        "candidates": result.get("candidates", []),
    }


def _price_freshness_bucket(raw_date: Any) -> str:
    if not raw_date:
        return "unknown"
    text = str(raw_date).strip().replace("T", " ")
    parsed = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            parsed = date.fromisoformat(text[:10]) if fmt == "%Y-%m-%d" else None
            if parsed is None:
                from datetime import datetime as _dt

                parsed = _dt.strptime(text[:19], fmt).date()
            break
        except Exception:
            continue
    if parsed is None:
        return "unknown"
    age = max(0, (date.today() - parsed).days)
    fresh_days = int((config.PRICE_FRESHNESS_RULES or {}).get("default_days_fresh", 30))
    stale_days = int((config.PRICE_FRESHNESS_RULES or {}).get("default_days_stale", 120))
    if age <= fresh_days:
        return "fresh"
    if age <= stale_days:
        return "stale"
    return "unknown"


def _quantity_break_multiplier(quantity: int) -> float:
    cfg = WORKBOOK_EQUIVALENT_PRICING or {}
    breaks = cfg.get("quantity_breaks") or []
    for br in breaks:
        qmin = int(br.get("min_qty", 1))
        qmax = br.get("max_qty")
        qmax_i = int(qmax) if qmax is not None else None
        if quantity >= qmin and (qmax_i is None or quantity <= qmax_i):
            return float(br.get("multiplier", 1.0))
    return 1.0


def _part_ops(part: Dict[str, Any]) -> List[str]:
    ops: List[str] = []
    for op in (part.get("textual_operations") or []) + (part.get("inferred_operations") or []):
        s = str(op).strip()
        if s and s not in ops:
            ops.append(s)
    # AN OPERATION THE ESTIMATOR HAS TAKEN OFF STAYS OFF.
    #
    # "Line 103 - Tube Bending Op. – Not Required." The drawing's text states a bend and
    # nothing measures one, so the engine charges it and asks — which is right, because
    # deleting charged work on one disagreement with one drawing is how a rule stops
    # describing anything. But once the person who knows has answered, the answer has to
    # survive the next run, and until now it did not: he deleted the row, we re-ran, and the
    # row came back.
    #
    # Stamped by file_scan from the job's own answers file, so it governs this drawing and
    # no other. The removal is recorded on the part, never silent.
    _off = (part.get("_estimator_operations_off") or [])
    if _off:
        # TWO SPELLINGS, ONE LETTER, AND THE RULING DOES NOTHING.
        #
        # The engine emits `tubebend` on the route and `tube_bending` in its own words, and
        # the example answers file spells it the second way. An estimator who copies that
        # file and rules the operation off gets no error and no effect — the strongest
        # evidence there is, silently discarded over an underscore. This is the same fault
        # that once made the tube-bender work for nothing, in the input layer instead of
        # the rate table.
        #
        # Matched on the letters, so any spelling of the same word answers to the ruling.
        def _spelling(_o: Any) -> str:
            return "".join(ch for ch in str(_o).lower() if ch.isalnum())
        _off_keys = {_spelling(o) for o in _off}
        _keep = [o for o in ops if _spelling(o) not in _off_keys]
        if len(_keep) != len(ops):
            _gone = [o for o in ops if o not in _keep]
            part.setdefault("removed_operations", []).extend(_gone)
            # AND UNDER THE NAME THE ROUTE READS, or the sheet rebuilds what the estimator
            # just struck off. The same two-names fault D-085 found on the tube-bend gate:
            # `removed_operations` cleans the COSTED record, while route_operations_by_part
            # and route_compiler both honour `operations_ruled_out` and nothing else. An
            # estimator's own ruling is the strongest evidence there is, and it was the one
            # most likely to be quietly rebuilt.
            _ruled = part.setdefault("operations_ruled_out", {})
            for _o in _gone:
                _ruled.setdefault(
                    _o, "the estimator took this operation off for this job "
                        "(estimator_decisions.operations_off in the job's answers file)")
        ops = _keep
    return ops


def _part_confidence_overall(part: Dict[str, Any]) -> Optional[float]:
    conf = part.get("confidence")
    if isinstance(conf, dict):
        v = _safe_float(conf.get("overall"))
        if v is not None:
            return v
        vals = [_safe_float(x) for x in conf.values() if _safe_float(x) is not None]
        if vals:
            return round(sum(vals) / len(vals), 4)
    return None


def _part_geometry_reliability(part: Dict[str, Any]) -> Optional[float]:
    return _safe_float(
        ((part.get("geometry_rollup") or {}).get("confidence") or {}).get("geometry_reliability")
    )


def _resolve_material_price(material: Optional[str], thickness_mm: Optional[float], quantity: Optional[int], part: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not material:
        return {"result": {}, "applied_price_per_kg": None, "applied_basis": None}

    result = get_best_price(
        PriceRequest(
            kind="material_price",
            material=material,
            thickness_mm=thickness_mm,
            quantity=quantity,
            description=str((part or {}).get("description") or ""),
            finish=_first((part or {}).get("surface_finishes", []) or []),
            colour=_first((part or {}).get("colours", []) or []),
            part_confidence_overall=_part_confidence_overall(part or {}),
            part_geometry_reliability=_part_geometry_reliability(part or {}),
        )
    )
    selected = _extract_selected_price(result)
    price = _selected_price_value(selected)
    unit = _selected_price_unit(selected)
    if price is None:
        return {"result": result, "applied_price_per_kg": None, "applied_basis": None}

    if is_per_kg_unit(unit):
        return {"result": result, "applied_price_per_kg": price, "applied_basis": "GBP_per_kg"}

    return {"result": result, "applied_price_per_kg": None, "applied_basis": None}


def _parse_section_profile(description: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Parse common section profile from description, e.g.:
    '25.00 x 25.00 x 1.50mm TUBE' -> (25.0, 25.0, 1.5)
    """
    text = str(description or "").upper().replace("MM", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)", text)
    if not m:
        return None, None, None
    return _safe_float(m.group(1)), _safe_float(m.group(2)), _safe_float(m.group(3))


def _lookup_catalogue_tube_price(
    side_a_mm: Optional[float],
    side_b_mm: Optional[float],
    wall_t_mm: Optional[float],
    length_mm: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Find a genuine catalogued price for a detected hollow section by matching its
    PROFILE (and length, when available) against priced rows in UDEF
    (dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING). SDI stocks slotted/cut tube as bought-in
    parts (e.g. SLOTTEDTUBE01/02 = 'ERW RECT. 60 x 30 x 1.5mm @ 1125mm/1072mm',
    £3.57 EA, Preferred Tubes Ltd), so a detected 60x30x1.5 @ 1125mm tube should price
    from that real catalogue row, NOT a generic mass*£/kg estimate.

    Matching is genuine: the catalogue description carries the profile and length, so we
    match on the two cross-section dims + wall, then prefer the row whose stated length is
    closest to the detected length. Returns the priced row (price, supplier, code, desc) or
    None — never raises, never invents a price.
    """
    if not (side_a_mm and side_b_mm and wall_t_mm):
        return None
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        # Normalise the two cross-section dimensions (order-independent: 60x30 == 30x60).
        _lo, _hi = sorted([round(side_a_mm), round(side_b_mm)])
        # Pull candidate priced section rows; match dims in Python (descriptions vary in format).
        cur.execute(
            """SELECT [Part code],[Description],[System cost per],[Supplier name],[UOM]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [System cost per] > 0
                 AND ([Description] LIKE '%TUBE%' OR [Part code] LIKE 'SLOTTEDTUBE%'
                      OR [Description] LIKE '%RECT%' OR [Description] LIKE '%RHS%' OR [Description] LIKE '%SHS%')"""
        )
        rows = cur.fetchall()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass

    best = None
    best_len_delta = None
    prof_re = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)")
    len_re = re.compile(r"(?:@|x|X)\s*(\d{2,5})\s*MM", re.IGNORECASE)
    for r in rows:
        code, desc, cost, supplier, uom = r[0], str(r[1] or ""), r[2], r[3], r[4]
        pm = prof_re.search(desc.upper())
        if not pm:
            continue
        d = sorted([round(float(pm.group(1))), round(float(pm.group(2))), float(pm.group(3))])
        # d = [wall, lo, hi] after sort (wall is smallest)
        cat_wall, cat_lo, cat_hi = d[0], round(d[1]), round(d[2])
        if not (cat_lo == _lo and cat_hi == _hi and abs(cat_wall - wall_t_mm) < 0.3):
            continue  # profile must match
        # Length proximity (if the catalogue row and the part both state a length).
        lm = len_re.search(desc.upper())
        cat_len = float(lm.group(1)) if lm else None
        if length_mm and cat_len:
            delta = abs(cat_len - length_mm)
        else:
            delta = 1e9  # no length to compare — weak match, keep only if nothing better
        # Prefer Preferred Tubes Ltd when multiple suppliers carry the same code/price.
        _pref = 0 if (supplier and "PREFER" in str(supplier).upper()) else 1
        key = (delta, _pref)
        if best is None or key < best_len_delta:
            best = {
                "part_code": code,
                "description": desc.strip(),
                "unit_price_gbp": float(cost),
                "supplier": str(supplier or "").strip(),
                "uom": str(uom or "").strip(),
                "catalogue_length_mm": cat_len,
            }
            best_len_delta = key

    # LENGTH GATE — a catalogue tube row is a specific bought-in cut piece at a stated stock
    # length (e.g. SLOTTEDTUBE 60x30x1.5 @1125mm). It is only a genuine price for a part of
    # THAT length. Without this gate a 1342mm cut and a 529.8mm cut of the same profile both
    # match the same row and take the same fixed price — which is exactly wrong (they should
    # differ by length). So when the PART length is known, only accept the catalogue price if
    # the catalogue length is within tolerance; otherwise return None so the caller costs by
    # the length-sensitive mass path (kg/m x length x £/kg) — honest, repeatable, per-length.
    if best is not None and length_mm:
        _cat_len = best.get("catalogue_length_mm")
        _tol = max(0.10 * length_mm, 75.0)
        if not (_cat_len and abs(float(_cat_len) - length_mm) <= _tol):
            return None
    return best


# Cache the HIPS rate table per-thickness for the duration of one run so we don't
# re-query UDEF for every HIPS part. Keyed by rounded thickness; value is £/m².
_SHEET_RATE_CACHE: Dict[Tuple[str, float], Optional[float]] = {}

# The researched £/m² for a board, by family and gauge, for the life of the run. Three parts
# cut from one sheet must not be researched three times and must not come back with three
# different rates for the same board — see `_researched_board_rate_m2`.
_RESEARCHED_BOARD_RATE_CACHE: Dict[Tuple[str, Optional[float]], Optional[Dict[str, Any]]] = {}

# Words that qualify a sheet rather than name it. "3MM CLEAR PETG SHEET" is PETG; searching
# the catalogue for CLEAR or SHEET would match half of it.
_NOT_A_MATERIAL_WORD = frozenset({
    "SHEET", "SHEETS", "PLATE", "PANEL", "BOARD", "STOCK", "MATERIAL", "GRADE",
    "CLEAR", "OPAL", "WHITE", "BLACK", "GREY", "GRAY", "MATT", "GLOSS", "SATIN",
    "TEXTURED", "SMOOTH", "MR", "FR", "EXT", "INT", "STD", "THK", "NOM",
})


# Premium / finished items. A rate built from printed, mirrored or vac-formed stock is a
# graphics price, not a sheet price.
_SHEET_RATE_EXCLUDE = ("PRINT", "MIRROR", "FLOCK", "VAC", "GOLD", "SILVER", "FOIL",
                       "GRAPHIC", "DIGITALLY", "SCREEN")
_SHEET_DIM_RE = re.compile(
    r"(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d(?:\.\d+)?)\s*mm",
    re.IGNORECASE)
_SHEET_RATE_MAX_GBP_PER_M2 = 60.0
_SHEET_RATE_MIN_AREA_M2 = 0.05


def _plain_stock_rates_gbp_per_m2(rows: Iterable[Any], token: str,
                                  thickness_key: float) -> List[float]:
    """Every catalogue row that is plain stock of THIS material at THIS gauge, as GBP/m2.

    A SEPARATE FUNCTION SO THE FILTER CAN BE TESTED. It used to be a loop inside a function
    whose first act is to open a database connection, so nothing could reach it without one --
    and a guard nothing can exercise is a guard nobody knows is working. A mutant that deleted
    the whole-word check survived every test in this file for exactly that reason.
    """
    # THE TOKEN AS A WHOLE WORD. SQL LIKE cannot say "word boundary", so '%ABS%' comes back
    # with every ABSORBER, ABSOLUTE and GLASSBOARD in the catalogue -- and a median built from
    # those is not wrong-looking, it is simply wrong, with nothing on the sheet to say so.
    word_re = re.compile(rf"\b{re.escape(token)}\b")
    rates: List[float] = []
    for r in rows or ():
        try:
            desc = str(r[1] or "")
            cost_raw = r[2]
        except (IndexError, TypeError):
            continue
        du = desc.upper()
        if not word_re.search(du):
            continue
        if any(bad in du for bad in _SHEET_RATE_EXCLUDE):
            continue
        m = _SHEET_DIM_RE.search(desc)
        if not m:
            continue
        try:
            L, W, T = float(m.group(1)), float(m.group(2)), float(m.group(3))
            cost = float(cost_raw)
        except (TypeError, ValueError):
            continue
        if round(T, 1) != thickness_key:
            continue
        area_m2 = (L * W) / 1_000_000.0
        if area_m2 < _SHEET_RATE_MIN_AREA_M2:      # tiny offcuts carry an inflated GBP/m2
            continue
        rate = cost / area_m2
        if rate <= 0 or rate > _SHEET_RATE_MAX_GBP_PER_M2:
            continue
        rates.append(rate)
    return rates


def _commercial_order_quantity(summary: Any) -> int:
    """How many of the assembly this order is for, for the packaging and delivery lines.

    file_scan stamps the order quantity onto summary['assumed_job_quantity'] (and 'quantity'),
    whichever way it was arrived at. The packaging and delivery lines divide a per-order figure
    by this, so reading the wrong key does not fail loudly — it silently divides by one. It did:
    the old read looked under summary['estimating_workbook'], a key nothing sets, so every order
    was divided by 1 and 400-off packaging landed at GBP 115 a unit instead of 29 pence. One
    reader of the order quantity, and it is the one file_scan wrote.
    """
    s = summary if isinstance(summary, dict) else {}
    for key in ("assumed_job_quantity", "quantity"):
        try:
            v = int(s.get(key))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return 1


# ── SUBCONTRACT PLATING ──────────────────────────────────────────────────────────────
# A PLATED weldment (7332-01's Harrods stand: title block "PLATED / Harrods 1") is finished by
# a subcontract plater, not through SDI's own powder booth. Its finish is therefore a subcontract
# line priced on the plated STEEL MASS x a trade £/kg, never a P.Coat booth-labour row (the
# powder gate already rules powder out on a plated part) and never the £0 it read before. The
# rate is an INDICATIVE trade-zinc figure that stays blocking until a plater quote confirms.

_PLATE_METAL_TOKENS = ("STEEL", "ALUMIN", "BRASS", "COPPER", "ZINTEC", "GALV", "METAL", "IRON")


def _is_plate_finish(text: Any) -> bool:
    """True when the drawing's finish words name a plating family (PLATED/ZINC/NICKEL/…)."""
    try:
        from finish_rules import finish_families
        return "plate" in finish_families(str(text or ""))
    except Exception:                                            # noqa: BLE001
        return False


def _is_plate_metal(text: Any) -> bool:
    return any(tok in str(text or "").upper() for tok in _PLATE_METAL_TOKENS)


def _part_finish_text(part: Dict[str, Any]) -> str:
    """Every word this part carries about its finish, normalised AND as drawn.

    THE `or` THAT COST HOWARD'S £—. This read the normalised fields and consulted the
    RAW list only when all of them were empty. A named spec is exactly the case where they
    are not: the finish classifier recognises "Harrods01" as a plate and writes its own word
    — "zinc plated" — into normalized_finish, and the drawing's actual callout stays in
    surface_finishes where nothing then looked. So 7332-01-101 priced on the indicative
    zinc card, £15.83 of trade plating against a quoted £— a stand: the largest single
    error on that sheet, by an order of magnitude, caused by an `or`.
    #
    The engine's word for a finish and the drawing's word for it are different facts and
    both are wanted. Joined, deduplicated, order preserved so the normalised token still
    reads first.
    """
    _seen = set()
    _out: List[str] = []
    for _v in (part.get("normalized_finish"), part.get("finish"),
               part.get("surface_finish"), *(part.get("surface_finishes") or [])):
        _s = str(_v or "").strip()
        if not _s or _s.upper() in _seen:
            continue
        _seen.add(_s.upper())
        _out.append(_s)
    return " ".join(_out)


def _part_material_text(part: Dict[str, Any]) -> str:
    return " ".join(str(v) for v in (
        part.get("normalized_material"), part.get("material"),
    ) if v) or " ".join(str(v) for v in (part.get("materials") or []))


def _child_parent_map(parts: Any, summary: Any) -> Dict[str, set]:
    """child part_number -> {parent part_numbers}, from the parts' own child lists and the LLM
    extract's assemblies. Best-effort; empty where the hierarchy is not stated."""
    parents: Dict[str, set] = {}

    def _add(parent: Any, child: Any) -> None:
        p = str(parent or "").strip().upper()
        c = str(child or "").strip().upper()
        if p and c:
            parents.setdefault(c, set()).add(p)

    for part in parts or []:
        if not isinstance(part, dict):
            continue
        pn = part.get("part_number")
        for ch in (part.get("assembly_children") or part.get("children") or []):
            _add(pn, ch.get("part_number") if isinstance(ch, dict) else ch)
    lex = (summary or {}).get("llm_full_extract") if isinstance(summary, dict) else {}
    for asm in ((lex or {}).get("assemblies") or []):
        if not isinstance(asm, dict):
            continue
        pn = asm.get("part_number")
        for ch in (asm.get("children") or []):
            _add(pn, ch.get("part_number") if isinstance(ch, dict) else ch)
    return parents


def _ancestors(pn: Any, parents: Dict[str, set], _seen: Optional[set] = None) -> set:
    pn = str(pn or "").strip().upper()
    _seen = _seen if _seen is not None else set()
    out: set = set()
    for p in parents.get(pn, ()):  # type: ignore[union-attr]
        if p in _seen:
            continue
        _seen.add(p)
        out.add(p)
        out |= _ancestors(p, parents, _seen)
    return out


def plated_steel_member_pns(parts: Any, summary: Any, parents: Any = None) -> set:
    """Every METAL part_number a plating finish covers: a part whose own finish is a plate
    family, or one that sits under a PLATED weldment (an assembly parent stated PLATED). Acrylic
    and board members are excluded — the plater does not plate the lens. The plated weldment
    line itself is not a member; its material lives in these children.

    `parents` is the hierarchy to read. Pass the COMPILED graph's map wherever one exists: the
    local fallback below only knows the parent's own child list and the LLM extract, and 7332-01
    proved that insufficient — the 002 -> 101 edge the Canonical BOM shows comes from the BOM
    table, so inheritance never fired and the only member named was 008, the one part that
    states PLATED on its own record. A member list that disagrees with the parent column an
    estimator reads is worse than no member list at all."""
    parents = parents if parents is not None else _child_parent_map(parts, summary)
    plated_weldments = {
        str(p.get("part_number") or "").strip().upper()
        for p in (parts or []) if isinstance(p, dict)
        and (p.get("is_assembly_parent") or p.get("is_sub_assembly"))
        and _is_plate_finish(_part_finish_text(p))
    }
    members: set = set()
    for part in (parts or []):
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "").strip().upper()
        if not pn or pn in plated_weldments:
            continue
        if not _is_plate_metal(_part_material_text(part)):
            continue
        _own = _part_finish_text(part)
        if _is_plate_finish(_own):
            members.add(pn)
            continue
        # A MEMBER'S OWN STATED FINISH OUTRANKS THE WELDMENT'S.
        #
        # Inheriting the parent's plate down every metal child swept in 7332-01's BASE 001,
        # which the drawing states RAW — about 5.3 kg of 5mm steel that no plater ever sees.
        # At £2.50/kg that is most of an £20.12 plate line charged for a part that is not
        # plated. A part that states a recognised finish of its own is not silently reassigned
        # to its parent's; only a member that states NOTHING inherits.
        try:
            from finish_rules import finish_families as _ff
            _fams = _ff(_own)
        except Exception:                                        # noqa: BLE001
            _fams = set()
        if _fams and "plate" not in _fams:
            continue                                             # stated RAW/bare/etc — not plated
        if _ancestors(pn, parents) & plated_weldments:
            members.add(pn)
    return members


def plated_members_deferred_to_their_own_finish(parts: Any, summary: Any,
                                                parents: Any = None) -> set:
    """Metal parts inside a PLATED weldment whose OWN detail states a different finish.

    THE ENGINE MUST NOT SETTLE THIS ONE. A weldment goes into the tank assembled, so every part
    welded into it is plated in practice — whatever its own detail sheet said about the part as
    supplied. 7332-01's leg 002 and base 001 both state RAW inside a PLATED weldment, and the
    honest answer is that this is a weldment-vs-leaf question for the estimator, not a rule.

    So the mass EXCLUDES them (never over-charge on an assumption) and the line NAMES them, so
    the person who knows can put them back. Deciding it silently in either direction is the
    failure mode: including them inflates a plate quote, excluding them quietly hides it behind
    a vat minimum that happens to produce the same number."""
    parents = parents if parents is not None else _child_parent_map(parts, summary)
    plated_weldments = {
        str(p.get("part_number") or "").strip().upper()
        for p in (parts or []) if isinstance(p, dict)
        and (p.get("is_assembly_parent") or p.get("is_sub_assembly"))
        and _is_plate_finish(_part_finish_text(p))
    }
    deferred: set = set()
    for part in (parts or []):
        if not isinstance(part, dict):
            continue
        pn = str(part.get("part_number") or "").strip().upper()
        if not pn or pn in plated_weldments:
            continue
        if not _is_plate_metal(_part_material_text(part)):
            continue
        own = _part_finish_text(part)
        if not own or _is_plate_finish(own):
            continue
        try:
            from finish_rules import finish_families as _ff
            fams = _ff(own)
        except Exception:                                            # noqa: BLE001
            fams = set()
        if fams and "plate" not in fams and (_ancestors(pn, parents) & plated_weldments):
            deferred.add(pn)
    return deferred


def named_plate_spec(finish_text: Any) -> Optional[Dict[str, Any]]:
    """The quoted plate spec this finish names, or None.

    Matched with spaces and punctuation removed, because one finish is written "Harrods01",
    "HARRODS 01" and "Harrods-01" across a pack. A finish that names no spec in the table
    returns None and the mass rate stands exactly as before."""
    _t = re.sub(r"[^A-Z0-9]+", "", str(finish_text or "").upper())
    if not _t:
        return None
    for _key, _spec in (getattr(config, "NAMED_PLATE_SPECS", {}) or {}).items():
        _k = re.sub(r"[^A-Z0-9]+", "", str(_key).upper())
        if _k and _k in _t:
            return dict(_spec, matched_spec=_key)
    return None


def inherited_decision(kind: str, facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The decision an estimator already made for conditions like these, or None.

    A DECISION MADE ONCE SHOULD NOT HAVE TO BE MADE AGAIN. Brass Harrods 01 went into
    7332-01's own answers file, which governs 7332-01 and nothing else — so the next Harrods
    stand states the same bare "PLATED", blocks for the same reason, and somebody types the
    same £—. Same characteristics, same manual work, every time.

    EVERY CONDITION MUST MATCH. An entry's `when` is a conjunction, and an entry with no
    conditions at all is refused rather than applied to everything — a rule that matches
    every job is not a rule, it is a default, and defaults belong in the policy tables where
    they can be seen.

    Strings compare case- and space-insensitively because "Harrods", "HARRODS" and
    "Harrods Ltd" are one customer; booleans compare exactly, because "the spec could not be
    identified" is not nearly true.

    Returns the entry's `then` with its provenance attached, so the caller can say on the
    line where the figure came from. Nothing here is silent: an inherited price that arrives
    without its history is indistinguishable from one the engine invented.
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, bool) or v is None:
            return v
        return re.sub(r"[^A-Z0-9]+", "", str(v).upper())

    def _norm_customer(v: Any) -> str:
        """One trading name, however the job folder spelled it.

        "Harrods", "Harrods Ltd" and "Harrods 7332-01" are one customer, and an inheritance
        rule that misses two of the three is the one-off hack it was written to replace. The
        job-code token is dropped by the same function the quote header already uses — the
        question "is this the same customer" must not grow a second answer — and the legal
        suffix is dropped here, which that function deliberately does not do because a quote
        heading should print the company's real name."""
        _s = str(v or "")
        try:
            from client_quote_html import _clean_customer_name as _ccn
            _s = _ccn(_s)
        except Exception:                                            # noqa: BLE001
            pass
        _s = re.sub(r"\b(LTD|LIMITED|PLC|LLP|INC|GROUP|HOLDINGS|UK|GB|CO)\b", " ",
                    _s.upper())
        return re.sub(r"[^A-Z0-9]+", "", _s)

    for _entry in (getattr(config, "INHERITED_ESTIMATOR_DECISIONS", []) or []):
        if not isinstance(_entry, dict):
            continue
        _when = _entry.get("when")
        if not isinstance(_when, dict) or not _when:
            continue                                  # no conditions is not "always"
        _then = _entry.get("then")
        if not isinstance(_then, dict) or kind not in _then:
            continue
        _hit = True
        for _k, _want in _when.items():
            _got = facts.get(_k)
            if isinstance(_want, bool) or isinstance(_got, bool) or _want is None:
                if _got != _want:
                    _hit = False
                    break
            elif _k == "customer":
                if not _norm_customer(_got) or \
                        _norm_customer(_got) != _norm_customer(_want):
                    _hit = False
                    break
            elif _norm(_got) != _norm(_want):
                _hit = False
                break
        if _hit:
            return dict(_then,
                        _decision_id=_entry.get("id") or "",
                        _decided_by=_entry.get("decided_by") or "an estimator",
                        _decided_on=_entry.get("decided_on") or "",
                        _decided_on_job=_entry.get("decided_on_job") or "",
                        _why=_entry.get("why") or "")
    return None


def job_customer(summary: Any) -> str:
    """The customer this job is for — the SAME answer the workbook header prints.

    TWO READERS, ONE FACT, AND I WROTE THE SECOND ONE AN HOUR AGO. The inherited-decision
    register keyed on `customer` and read two fields. The workbook header reads four, and on
    7332-01 the name comes from the FOURTH: the pack sits in a Harrods folder, nothing on any
    drawing says Harrods, and client_from_job_folder is what recovers it — a function written
    for this exact estimator request ("can Client / Job Description / Date be populated for
    header").

    So the sheet said Harrods, the register looked for Harrods and found "", and the £— did
    not apply to a job that plainly qualified. Exactly the defect class this session has spent
    the evening on: a second reader that agrees with the first until the one case where it
    matters.

    Delegated rather than copied. If the header's rule changes, this changes with it.
    """
    if not isinstance(summary, dict):
        return ""
    _direct = str(summary.get("customer") or summary.get("client") or "").strip()
    if _direct:
        return _direct
    try:
        from wb_populate import client_from_job_folder as _cjf
        return str(_cjf(summary) or "").strip()
    except Exception:                                                # noqa: BLE001
        return ""


def plater_freight_for_job(job_codes: Any) -> Optional[Dict[str, Any]]:
    """THIS job's plater freight quote from the register, or None.

    The £— was 7332-01's own transport quote, and holding it in config made it every
    plated job's freight — the same fault as the £—, in a smaller coat. The register
    holds it scoped job_only, so this returns a figure ONLY for the job it was quoted for;
    every other plated job gets None and the caller writes an owned gap naming SDI
    transport, never a borrowed number.
    """
    try:
        import price_register
    except Exception:                                                # noqa: BLE001
        return None
    entry = price_register.lookup("PLATER_FREIGHT", job_codes or ())
    if entry and entry.get("chargeable") and (_safe_float(entry.get("amount")) or 0) > 0:
        return entry
    return None


def customer_finish_standard(customer: Any) -> Optional[Dict[str, Any]]:
    """The finish standard SDI has learned for this customer, or None.

    "M&S dress all seen welds; TTI none" — Howard Thurley, 15 Sep 2026. A fact about the
    customer, kept as a rule with his name on it (config.CUSTOMER_FINISH_STANDARDS), never
    a price. Matched on the normalised trading name so "M&S", "Marks & Spencer" and a job
    folder's spelling are one customer; a customer not in the table gets None and the shop
    default stands.
    """
    _table = getattr(config, "CUSTOMER_FINISH_STANDARDS", None) or {}
    if not _table:
        return None

    def _norm(text: Any) -> str:
        _s = re.sub(r"\b(LTD|LIMITED|PLC|LLP|INC|GROUP|HOLDINGS|UK|GB|CO|AND)\b", " ",
                    str(text or "").upper())
        return re.sub(r"[^A-Z0-9]+", "", _s)

    _want = _norm(customer)
    if not _want:
        return None
    for _name, _std in _table.items():
        if _norm(_name) != _want:
            continue
        _alias = (_std or {}).get("alias_of")
        if _alias:
            _std = _table.get(_alias) or {}
            _name = _alias
        if not isinstance(_std, dict) or "dress_visible_welds" not in _std:
            return None
        return dict(_std, customer=_name)
    return None


def named_plate_spec_anywhere_on_the_pack(
        *record_lists: Any) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """A registered plate spec named on ANY part of this pack: (spec, part_number, text).

    THE CALLOUT IS ON THE PACK, NOT NECESSARILY ON THE LINE THAT PAYS FOR IT. 7332-01's
    plating line is synthesised against the weldment and its members, and the finish those
    records carried read "PLATED" — while the estimator's own account of the drawing is
    that it "only nominates a finish as Harrods01". A general note, a GA title block and a
    BOM finish column are all places a pack states a finish once for the whole job, and a
    reader that only ever looks at the plated members will miss every one of them.

    So the search widens to the pack and STOPS THERE. It is the pack's text that is read —
    never the customer's name, never the job number, never a folder. A spec found this way
    is a token the drawing set actually contains; a job containing no registered token
    finds nothing, which is every job but the ones we hold a quote for.

    The part it was found on comes back with it, because a price taken from another part's
    finish field has to say which part, or an estimator cannot check it.
    """
    for _records in record_lists:
        for _rec in (_records or []):
            if not isinstance(_rec, dict):
                continue
            _text = _part_finish_text(_rec)
            _spec = named_plate_spec(_text)
            if _spec:
                return _spec, str(_rec.get("part_number") or "?"), _text
    return None, "", ""


def job_identity_codes(summary: Any) -> Tuple[str, ...]:
    """Every job code this job answers to — its drawing number, its output stem, its folder.

    Used to decide whether a figure quoted FOR a job belongs to the job in hand. Reuses the
    confirmations lookup's own reader so "is this the same job?" has one answer in this
    codebase rather than two that can drift apart.
    """
    try:
        from estimator_confirmed import job_codes as _codes
    except Exception:                                                # noqa: BLE001
        return ()
    out: List[str] = []
    if not isinstance(summary, dict):
        return ()
    for _text in (summary.get("declared_product"),
                  (summary.get("document_analysis") or {}).get("drawing_number"),
                  summary.get("drawing_number"), summary.get("job_output_stem"),
                  str(summary.get("job_folder") or "").replace("\\", "/").split("/")[-1]):
        for _c in _codes(_text):
            if _c not in out:
                out.append(_c)
    return tuple(out)


def _quote_belongs_to_this_job(spec: Dict[str, Any], job_codes_here: Any) -> bool:
    """Is this named spec's figure a price for the job in hand, or another job's quote?

    Howard Thurley, 16 Sep 2026: "Plating would be as drawing specific, £— is from
    supplier per unit and is independent of any other job. Plating jobs priced
    independently." A spec marked `priced_per_job` therefore prices ONLY the job it was
    quoted for; anywhere else the spec is still identified and the figure is still shown,
    but as that job's quote and not as this job's price.

    A job we cannot identify is NOT a match — the safe direction is to ask for a quote, not
    to apply somebody else's.
    """
    if not spec.get("priced_per_job"):
        return True
    _for = str(spec.get("quoted_for_job") or "").strip()
    if not _for:
        return False
    try:
        from estimator_confirmed import _same_job_code as _same
    except Exception:                                                # noqa: BLE001
        return False
    return any(_same(_for, _c) for _c in (job_codes_here or ()))


def plating_unit_price(mass_kg: Any, order_qty: Any,
                       policy: Dict[str, Any],
                       finish_text: Any = "",
                       job_codes_here: Any = ()) -> Tuple[Optional[float], str, str]:
    """Per-unit subcontract plating cost from the plated mass, honouring the plater's per-batch
    vat minimum. Returns (unit_gbp or None, note, cost_method). None where no rate is configured
    or no mass resolved — the caller then keeps the line as a blocking 'estimator to price'.

    A NAMED SPEC IS A QUOTED PRICE AND COMES FIRST. The policy's own note says a decorative
    or named plate spec is not the per-kilo rate; 7332-01 is that case, its requirement is
    Brass Harrods 01, and the plater charges £— a stand against an indicative zinc line of
    a few pounds on mass. Keyed on the finish the drawing names, so a job calling up no such
    spec is priced exactly as it was."""
    _spec = named_plate_spec(finish_text)
    if _spec:
        # A NAMED SPEC IS A METHOD, AND THE PRICE IS ASKED OF SDI'S OWN SOURCES.
        #
        # "The engine must learn methods, conditions, and evidence, not copy a manual
        # estimate's numbers into the next estimate" — James Gray, 16 Sep 2026. What this
        # entry teaches is that "Harrods 01" is a DECORATIVE requirement, so the per-kilo
        # zinc card must not price it (the original defect, an order of magnitude out), and
        # that a plater quotes it per job. The figure comes from the price sources at run
        # time, like the tape's roll price — never from a literal in config.
        _code = str(_spec.get("matched_spec") or "").strip()
        _live_gbp, _live_label = None, ""
        try:
            import stated_prices as _sp
            _px = _sp.resolve(_code, _spec.get("label") or "")
            if _px and _safe_float(_px.get("gbp")):
                _live_gbp = round(float(_px["gbp"]), 2)
                _live_label = str(_px.get("label") or "")
        except Exception:                                            # noqa: BLE001
            _live_gbp = None
        if _live_gbp:
            return (_live_gbp,
                    f"{_spec.get('label') or _code} — £{_live_gbp:.2f} per unit, the current "
                    f"price for the named spec and not the per-kilo rate ({_live_label or 'source not named'})",
                    "subcontract_plating_named_spec")
        if _spec.get("requires_quote"):
            # NO LIVE PRICE — SO THE LAST QUOTE PRICES IT, LABELLED AS WHAT IT IS.
            #
            # The first cut of this returned None, and a plating line at £0 understates the
            # sheet by whatever the plating costs, which on a decorative brass is most of
            # the unit. The pricing policy is explicit about the choice: "where the source is
            # old, missing or inferred, the estimate still prices the work and explains that
            # basis rather than silently omitting it", and a previous job's figure "may
            # provide a transparent historical comparator, but must not become an UNLABELLED
            # automatic price".
            #
            # So it prices, and every word of the label is the difference between the two:
            # the job it was quoted for, the date, the supplier, and that it is a comparator
            # to be replaced. Source priority is intact — SDI Live was asked first and could
            # not answer; a figure in this job's answers file outranks this line entirely.
            # A NEW ESTIMATE IS INDEPENDENT OF AN OLD ONE — NO COMPARATOR, NO FALLBACK.
            #
            # This priced from the last quote we held, labelled as a historical comparator.
            # James Gray, 16 Sep 2026, on reading it: "we don't know about the [plater figure] as our
            # estimating process is as independent as it can be… it should not appear in a
            # new estimate at all — not as a charge, fallback, comparator, workbook note or
            # suggested value." He is right, and the label did not save it: a figure on the
            # line is a figure somebody accepts.
            #
            # WHAT 7332-01 TAUGHT IS KEPT, AND IT IS NOT A NUMBER: that "Harrods 01" is
            # DECORATIVE plating, so the per-kilo zinc card cannot price it (the original
            # order-of-magnitude defect), and that a requirement of this kind needs a
            # fresh job-specific quote. The figure itself is retained NOWHERE — James
            # Gray, 16 Sep 2026: a number copied from an estimator's sheet is not kept in
            # the register, documentation, reports, prompts, tests or audit payloads.
            #
            # The rungs below a live price are, in order: a confirmed figure for THIS job
            # (the answers file, which outranks everything here); a labelled market estimate
            # — NOT CONNECTED for a named PROCESS, because the market path prices parts off
            # a drawing and nothing asks it what a plater charges for a finish; then this.
            # "No silent gaps" requires the last state to name what is missing and who is
            # being asked, so it does.
            # RUNG 5, AND ONLY AFTER THE OTHERS. The source hierarchy for this line is:
            #   1  live SDI / UDEF or supplier price          — asked above
            #   2  a confirmed figure for THIS job            — the answers file, outranks all
            #   3  a matched historical quote, labelled       — the branch above
            #   4  a market estimate, labelled indicative     — NOT CONNECTED for a named
            #      PROCESS: the market path prices parts off a drawing, and nothing asks it
            #      what a plater charges for a finish. Declared, not pretended.
            #   5  awaiting a quote — here
            # "No silent gaps" requires this last state to name the missing information and
            # who is being asked for it, so it does.
            return (None,
                    f"{_spec.get('label') or _code} — a named decorative plating "
                    f"requirement, NOT the zinc/passivate card, and NOT PRICED. "
                    f"MISSING: a current price for this spec. Nothing in SDI Live answered "
                    f"for it and no figure for this job has been entered. An earlier job's "
                    f"quote is NOT used here — plating is priced job by job and this "
                    f"estimate is independent of any other. ASKED OF: the estimator — get "
                    f"the plater's price for this job and enter it in this job's answers "
                    f"file. "
                    f"{_spec.get('confirm') or ''}".strip(),
                    "subcontract_plating_quote_needed")
        if _safe_float(_spec.get("gbp_per_unit")):
            _unit = round(float(_spec["gbp_per_unit"]), 2)
            if not _quote_belongs_to_this_job(_spec, job_codes_here):
                return (None,
                        f"{_spec.get('label') or _code} — the spec is identified but NOT "
                        f"PRICED here. £{_unit:.2f} a unit is the quote for "
                        f"{_spec.get('quoted_for_job') or 'another job'} "
                        f"({_spec.get('source', 'source not recorded')}), and "
                        f"{_spec.get('confirm') or 'plating is quoted job by job'}",
                        "subcontract_plating_quote_needed")
            return (_unit,
                    f"{_spec.get('label') or _code} — £{_unit:.2f} per unit, "
                    f"a quoted price for the named spec and not the per-kilo rate "
                    f"({_spec.get('source', 'source not recorded')})",
                    "subcontract_plating_named_spec")
    rate = (policy or {}).get("gbp_per_kg")
    if rate in (None, ""):
        return None, "no plating rate configured — estimator to price", "estimator_to_price"
    mass = _safe_float(mass_kg) or 0.0
    if mass <= 0:
        return (None, "plated mass could not be derived from the members — estimator to price",
                "estimator_to_price")
    q = max(1, int(order_qty or 1))
    vat_min = float((policy or {}).get("vat_minimum_gbp") or 0.0)
    line_cost = mass * float(rate) * q
    order_cost = max(line_cost, vat_min)
    unit = round(order_cost / q, 2)
    hit_min = order_cost > line_cost + 1e-9
    note = (f"{mass:.1f} kg plated × £{float(rate):.2f}/kg"
            + (f", plater vat minimum £{vat_min:.0f} spread over {q} off" if hit_min
               else f" × {q} off")
            + " — INDICATIVE zinc/passivate, verify against a plater quote")

    # ---- AND THE CARD ONLY PRICES THE PLATING IT IS A CARD FOR --------------------
    #
    # "Line 20 – Plating stated as Zinc – Requirement is Brass Harrods 01 (£— per each
    # stand.)" The engine had not stated zinc because it read zinc. It stated zinc because
    # zinc is what this rate is, and it applied the rate to a drawing whose finish field says
    # only "PLATED" — a word that names a family and no process inside it.
    #
    # £2.50/kg is a trade zinc-and-passivate card. Against a decorative brass it is not an
    # approximation, it is a different product: the engine's own zinc-card figure against the plater's quote, an order of magnitude apart, on a
    # line an estimator has no reason to look twice at because it carries a plausible number
    # and the word INDICATIVE. A wrong figure that reads as considered is worse than a blank,
    # and this is the shape of wrong that survives review.
    #
    # So the card prices what the card covers, and an unidentified plate goes to the person
    # who can ring the plater — carrying the card's arithmetic as a CANDIDATE, and every
    # quoted spec we hold beside it, so accepting one is a decision and not a retype.
    _covers = tuple((policy or {}).get("rate_covers") or ())
    _fin_u = str(finish_text or "").upper()
    if _covers and not any(str(tok).upper() in _fin_u for tok in _covers):
        _named = str(finish_text or "").strip() or "not stated"
        # THE SPECS WE KNOW, WITH WHAT THEY LAST COST — offered so an estimator can say
        # "that one" rather than start from the drawing again. The figure is the LAST QUOTE
        # and reads as one: the entries themselves carry no chargeable rate any more.
        # THE SPECS WE KNOW, WITH WHAT THEY LAST COST — offered so an estimator can say
        # "that one" rather than start from the drawing again. The figures come from the
        # price register, because that is where money lives; config holds only the method.
        def _spec_quote(_key, _s):
            try:
                import price_register as _pr
                _e = _pr.lookup(_key, job_codes_here)
                if _e and _safe_float(_e.get("amount")):
                    _sc = (_e.get("scope") or {}).get("value") or ""
                    return (round(float(_e["amount"]), 2),
                            f"last quoted{(' for ' + _sc) if _sc else ''} on "
                            f"{_e.get('source_date') or 'an unrecorded date'} — "
                            f"{_e.get('source_reference') or 'source not recorded'}")
            except Exception:                                        # noqa: BLE001
                pass
            return None, ""

        _rows = []
        for _k, _s in (getattr(config, "NAMED_PLATE_SPECS", {}) or {}).items():
            _amt, _where = _spec_quote(_k, _s)
            if _amt:
                _rows.append(f"{(_s.get('label') or _k)} £{_amt:.2f} per unit ({_where})")
        _cands = "; ".join(_rows)
        return (None,
                f"PLATING SPEC NOT IDENTIFIED — the drawing's finish reads {_named!r}, which "
                f"names a plate but not which plate. The £{float(rate):.2f}/kg card is trade "
                f"zinc/passivate and prices nothing else: on this mass it would be "
                f"£{unit:.2f} a unit ({note}) — that figure is a CANDIDATE and is NOT "
                f"charged. Quoted specs on file: "
                + (_cands or "none")
                + ". Confirm the process with the plater and enter the price, or accept the "
                  "zinc candidate deliberately",
                "subcontract_plating_spec_unidentified")

    return unit, note, "subcontract_plating_indicative"


def _member_mass_kg(pe: Dict[str, Any]) -> float:
    me = pe.get("material_estimate") or {}
    m = (_safe_float(me.get("unit_material_mass_kg"))
         or _safe_float((pe.get("cost_breakdown", {}).get("material", {}) or {}).get(
             "unit_material_mass_kg")) or 0.0)
    q = _safe_float(pe.get("quantity")) or 1.0
    return m * q


def _compiled_parent_map(parts: Any, summary: Any) -> Dict[str, set]:
    """The parent map the CANONICAL BOM will show, from the compiler itself.

    Built by the same build_part_graph the workbook reads, so a member list derived from it
    cannot disagree with the parent column beside it. Returns {} if the graph cannot be built —
    the caller then falls back to the local reading rather than losing the line."""
    try:
        import route_compiler as _rc
        _g = _rc.build_part_graph(
            [p for p in (parts or []) if isinstance(p, dict)],
            (summary or {}).get("llm_full_extract") or {} if isinstance(summary, dict) else {},
            declared_product=_rc.declared_product_of(summary if isinstance(summary, dict)
                                                     else {}))
        return {str(k).strip().upper(): {str(v).strip().upper() for v in (vs or set())}
                for k, vs in (_g.get("parents") or {}).items()}
    except Exception as exc:                                         # noqa: BLE001
        print(f"   [plating] could not compile the hierarchy for the member list ({exc}); "
              f"falling back to the stated one", flush=True)
        return {}


def apply_subcontract_plating(part_estimates: List[Dict[str, Any]], summary: Any,
                              order_qty: Any, parts: Any = None) -> int:
    """Price the plating placeholder line(s) from the members' own costed masses, AFTER the part
    loop so the figure agrees with the sheet. A resolved mass gives an INDICATIVE price; an
    unresolved one leaves the line as a named blocking gap — never a silent £0."""
    policy = getattr(config, "PLATE_SUBCONTRACT_POLICY", {}) or {}
    by_pn = {str(pe.get("part_number") or "").strip().upper(): pe for pe in part_estimates}
    # RE-DERIVE THE MEMBERS FROM THE HIERARCHY THE SHEET WILL SHOW. The list stamped at mint
    # time was read from the parent's own child list and the LLM extract — neither of which
    # carried 7332-01's 002 -> 101 edge (the BOM table did), so inheritance never fired and the
    # plate named only 008, the part that states PLATED itself. Recomputing here, after the
    # parts are costed and against the compiled graph, makes the member list and the Canonical
    # BOM's parent column two views of one fact instead of two opinions.
    _graph_parents = _compiled_parent_map(parts if parts is not None else part_estimates, summary)
    if _graph_parents:
        try:
            _regathered = plated_steel_member_pns(
                parts if parts is not None else part_estimates, summary, _graph_parents)
        except Exception:                                            # noqa: BLE001
            _regathered = set()
        if _regathered:
            for _pe in part_estimates:
                if _pe.get("_plating_placeholder"):
                    _pe["_plating_members"] = sorted(_regathered)
    priced = 0
    for pe in part_estimates:
        if not pe.get("_plating_placeholder"):
            continue
        members = {str(m).strip().upper() for m in (pe.get("_plating_members") or [])}
        # NAME WHO IS IN THE MASS. £20.12 is only checkable if the line says which parts the
        # plater is quoted for — an estimator cannot confirm a plated weight against a number
        # with no member list, and a RAW part wrongly swept in is invisible without it.
        _contrib = sorted(m for m in members if m in by_pn and _member_mass_kg(by_pn[m]) > 0)
        try:
            _deferred = sorted(plated_members_deferred_to_their_own_finish(
                parts if parts is not None else part_estimates, summary,
                _graph_parents or None))
        except Exception:                                            # noqa: BLE001
            _deferred = []
        mass = sum(_member_mass_kg(by_pn[m]) for m in members if m in by_pn)
        # THE FINISH THE DRAWING NAMES, from the weldment this line plates and from its
        # members — a named spec is stated on whichever of them carries the finish callout,
        # and reading only one of the two is how "Harrods 01" goes unseen on a line that
        # exists because of it.
        # ── THE ESTIMATOR'S OWN PRICE, IF HE HAS GIVEN ONE ─────────────────────────────
        #
        # "Line 20 – Plating stated as Zinc – Requirement is Brass Harrods 01 (£— per
        # each stand.)" The spec is not written on the drawing — every finish field in the
        # pack reads PLATED — so no amount of reading gets the engine there, and the line
        # correctly blocks. What it needed was somewhere for his answer to live that is not
        # a code change by us and not an overtype that dies with the workbook.
        #
        # This is his figure, applied as his, named as his, and it governs this job only:
        # the file is named for the drawing, so the next Harrods stand asks again rather
        # than inheriting a price nobody re-checked.
        _dec = (summary or {}).get("estimator_decisions") or {} \
            if isinstance(summary, dict) else {}
        # Bound before either branch: the description block below reads it, and only one of
        # the two paths assigns it. An unbound name here is a NameError on the one run that
        # takes the other path, which is the class of defect the name-resolution gate exists
        # to catch and the kind that reaches a live job.
        _inh: Optional[Dict[str, Any]] = None
        _dec_plate = _safe_float(_dec.get("plating_gbp_per_unit"))
        if _dec_plate and _dec_plate > 0:
            _who = _dec.get("decided_by") or "an estimator"
            _when = f", {_dec['decided_on']}" if _dec.get("decided_on") else ""
            _spec_lbl = str(_dec.get("plating_spec") or "").strip()
            unit = round(float(_dec_plate), 2)
            note = (f"{_spec_lbl + ' — ' if _spec_lbl else ''}£{unit:.2f} per unit, "
                    f"{_who}'s own figure for this job{_when} "
                    f"(from {_dec.get('decided_in', 'the estimator answers file')}). NOT a "
                    f"rate this engine sourced and not read off the drawing — the pack states "
                    f"only a plate family. It governs this drawing alone")
            method = "estimator_stated_price"
            _found_on = ""
        else:
            _finish_src = [pe.get("_plating_weldment")] + sorted(members)
            _finish_text = " ".join(
                _part_finish_text(by_pn[str(m).strip().upper()])
                for m in _finish_src
                if m and str(m).strip().upper() in by_pn)
            # AND IF NEITHER OF THEM NAMES A SPEC, ASK THE REST OF THE PACK.
            # A finish stated once for the whole job — on a GA title block, a general note,
            # the BOM's own finish column — is on no plated member's record, and reading only
            # the members is how "Harrods01" went unseen on the line that exists for it.
            _found_on = ""
            if not named_plate_spec(_finish_text):
                _spec_pack, _found_on, _spec_text = named_plate_spec_anywhere_on_the_pack(
                    part_estimates, parts if parts is not None else [])
                if _spec_pack:
                    _finish_text = f"{_finish_text} {_spec_text}".strip()
            unit, note, method = plating_unit_price(
                mass, order_qty, policy, _finish_text, job_identity_codes(summary))
            if _found_on and method == "subcontract_plating_named_spec":
                note += (f". The spec is not stated on this weldment or its members — it was "
                         f"read from {_found_on}'s own finish on this pack; confirm it "
                         f"governs the plated members listed here")
            # ── AND A DECISION ALREADY MADE FOR CONDITIONS LIKE THESE ──────────────────
            #
            # The pack could not identify the spec, so the line blocks — which is right, and
            # on the SECOND Harrods stand it is also useless: it blocks for exactly the
            # reason it blocked the first time, and somebody types £— again. A rule that
            # produces the same manual work on every drawing with the same characteristics
            # is not a rule.
            #
            # Only consulted where the pack has NOT answered. A drawing that names its own
            # spec is read, never overruled by something an estimator said about a different
            # job, and a priced line is left alone entirely.
            if method == "subcontract_plating_spec_unidentified":
                _inh = inherited_decision("plating_gbp_per_unit", {
                    "customer": job_customer(summary),
                    "finish_family": "plate",
                    "spec_identified": False,
                })
                if _inh and _safe_float(_inh.get("plating_gbp_per_unit")):
                    _prev_note = note
                    unit = round(float(_inh["plating_gbp_per_unit"]), 2)
                    method = "inherited_estimator_decision"
                    note = (
                        f"{_inh.get('plating_spec') or 'as previously decided'} — "
                        f"£{unit:.2f} per unit, INHERITED from a decision "
                        f"{_inh['_decided_by']} made on {_inh['_decided_on_job']}"
                        f"{' (' + _inh['_decided_on'] + ')' if _inh['_decided_on'] else ''}: "
                        f"{_inh.get('_why') or 'no reason recorded'}. THIS DRAWING DOES NOT "
                        f"STATE THE SPEC — it states a plate and no process, and this figure "
                        f"comes from the earlier job, not from the pack in front of you. "
                        f"Confirm it applies to this stand. Without it the line would read: "
                        f"{_prev_note}")
        # GETTING IT THERE AND BACK IS PART OF HAVING IT PLATED.
        #
        # "Delivery to & from Platers from Transport Dept. For Ref. £— Pallet Network -
        # £— per unit." Freight the job would not incur if the part were finished in
        # house, and it was on no line at all. It rides on the plating line rather than a new
        # commercial line of its own, because that is the cause of it and an estimator
        # reading "plating" should see what plating costs.
        #
        # Held per ORDER with the per-unit share derived, which is the form that survives a
        # quantity change: £— over the six stands the figure was quoted against is his £20
        # a unit. Whether £— is the round trip or each way the note does not settle, so the
        # line says which it assumed.
        # AND IT IS NOT ADDED TO THIS LINE, DELIBERATELY. Freight to and from the plater is
        # real money the job would not spend if the part were finished in house, but this
        # line has to equal what the PLATER charges or an estimator cannot check it against
        # the plater's own quote — which is the whole reason the named spec is priced as a
        # quote. So the figure is carried on the record and stated in the note, for the
        # delivery line and for the person reading it, and the plating price stays plating.
        _fr_entry = plater_freight_for_job(job_identity_codes(summary))
        if unit is not None and _fr_entry:
            import price_register as _preg
            _freight_order = _safe_float(_fr_entry.get("amount")) or 0.0
            _q = max(1, int(order_qty or 1))
            _freight_unit = round(_freight_order / _q, 2)
            pe["plater_freight_gbp_per_unit"] = _freight_unit
            pe["plater_freight_gbp_per_order"] = _freight_order
            note += (f". NOT INCLUDED here: freight to and from the plater, "
                     f"£{_freight_order:.0f} the round trip"
                     f" = £{_freight_unit:.2f} a unit at {_q} off — put it on the delivery "
                     f"line ({_preg.describe(_fr_entry)})")
        elif unit is not None:
            # AN OWNED GAP, NOT A BORROWED FIGURE. The part goes out and comes back, so the
            # freight is real money — and no current transport quote for THIS job is on
            # record. An earlier job's quote is that job's and does not price this one.
            note += (". NOT INCLUDED and NOT PRICED: freight to and from the plater needs "
                     "a CURRENT transport quote for this job — MISSING: the haulage figure; "
                     "ASK: SDI transport department")
        qty = max(1, int(pe.get("quantity") or 1))
        ext = round((unit or 0.0) * qty, 2)
        pe["unit_material_cost_gbp"] = unit or 0.0
        pe["unit_cost_gbp"] = unit or 0.0
        pe["unit_total_cost_gbp"] = unit or 0.0
        pe["extended_total_cost_gbp"] = ext
        pe["material_estimate"] = {
            "unit_material_cost_gbp": unit or 0.0,
            "cost_per_part_gbp": unit or 0.0,
            "extended_material_cost_gbp": ext,
            "unit_material_mass_kg": round(mass, 3),
            "cost_method": method,
        }
        pe["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        pe["cost_source"] = method
        pe["source"] = method
        pe["price_verified"] = False
        pe["review_flag"] = True
        pe["_price_explicitly_withheld"] = unit is None
        pe["_plating_members_costed"] = _contrib
        pe["_plating_members_deferred"] = _deferred
        # THE OPEN QUESTION GOES ON THE LINE, NOT INTO A DECISION.
        #
        # A weldment goes into the tank assembled, so a part welded into a PLATED weldment is
        # plated in practice even where its own detail says RAW — but that is the estimator's
        # weldment-vs-leaf call, not a rule this engine gets to apply. The mass excludes them
        # (never over-charge on an assumption) and the line NAMES them so the person who knows
        # can put them back. Silently excluding is as wrong as silently including: it hides the
        # question behind a vat minimum that happens to produce the same number either way.
        pe["review_flags"] = [
            note
            + (f" ; plated members: {', '.join(_contrib)}" if _contrib
               else " ; no plated member resolved a mass")
            + (f" ; NOT included, own detail states another finish: {', '.join(_deferred)} — "
               f"a weldment is plated assembled, so if these go in the tank they belong in the "
               f"mass; weldment-vs-leaf is your call" if _deferred else "")
            + " ; confirm the process (trade zinc vs a named Harrods plate spec — "
              "nickel is not this rate) and that this member list is what the plater quotes"]
        # The member list on the DESCRIPTION too, so it survives onto the sheet line itself and
        # not only into a review flag an estimator has to go looking for.
        # AND THE LINE STOPS CALLING ITSELF ZINC WHEN IT IS NOT PRICED AS ZINC.
        # The placeholder is minted with the policy's own label — "INDICATIVE
        # zinc/passivate" — because at mint time the only rate in view is the card. Once the
        # spec turns out to be unidentified, that label is the single most misleading string
        # on the sheet: it names a process the drawing never stated, on a line carrying no
        # money, in the description column an estimator reads first.
        if method == "subcontract_plating_spec_unidentified":
            _pn_plate = str(pe.get("_plating_weldment") or pe.get("part_number") or "").strip()
            pe["description"] = (
                f"{_pn_plate} plating — SPEC NOT IDENTIFIED: the drawing names a plate but "
                f"not which plate. NOT PRICED — confirm the process with the plater").strip()
        elif method == "subcontract_plating_historical_comparator":
            # THE LABEL IS THE WHOLE DIFFERENCE, SO IT HAS TO REACH THE SHEET. A comparator
            # that prices £— and reads "plating" in the description column is an unlabelled
            # standing rate by the time an estimator sees it, whatever the note said upstream.
            _pn_plate = str(pe.get("_plating_weldment") or pe.get("part_number") or "").strip()
            pe["description"] = f"{_pn_plate} plating — {note}".strip()
        elif method == "subcontract_plating_quote_needed":
            # THE SPEC IS KNOWN AND THE PRICE IS NOT OURS TO REUSE. Distinct from the
            # unidentified case on purpose: there the question is "which plate?", here it
            # is "what does the plater charge for it on THIS job?" — and a description that
            # confused the two would send an estimator to the drawing instead of the phone.
            _pn_plate = str(pe.get("_plating_weldment") or pe.get("part_number") or "").strip()
            pe["description"] = (
                f"{_pn_plate} plating — {note}").strip()
        elif method == "inherited_estimator_decision":
            _pn_plate = str(pe.get("_plating_weldment") or pe.get("part_number") or "").strip()
            _inh_lbl = str((_inh or {}).get("plating_spec") or "").strip()
            pe["description"] = (
                f"{_pn_plate} plating — {_inh_lbl or 'as previously decided'}, INHERITED from "
                f"{(_inh or {}).get('_decided_on_job') or 'an earlier job'} — confirm it "
                f"applies here").strip()
        elif method == "estimator_stated_price":
            # AND THE LINE SAYS WHOSE PRICE IT IS. A figure a person set must never read on
            # the sheet like one the engine sourced — that is the rule the answers file was
            # built on, and it is worth nothing if the description still says zinc.
            _pn_plate = str(pe.get("_plating_weldment") or pe.get("part_number") or "").strip()
            _spec_lbl2 = str(_dec.get("plating_spec") or "").strip()
            pe["description"] = (
                f"{_pn_plate} plating — {_spec_lbl2 or 'as specified'}, "
                f"{_dec.get('decided_by') or 'the estimator'}'s stated price").strip()
        # ── WHEN THE PRICE IS PER STAND, THE MEMBER LIST IS THE WHOLE WELDMENT ──────────
        #
        # The exclusion exists because the mass decides the money on the £/kg card: a member
        # whose own detail says RAW must not be swept into a weight nobody agreed. That is
        # right, and on a QUOTED price it is answering a question nobody asked. £— is per
        # stand. The mass is not an input, so excluding a member changes no figure — it only
        # leaves an audit list saying the plater is quoted for 7332-01-008 alone, when what
        # goes in the tank is the welded frame.
        #
        # A list that is wrong in a direction that costs nothing is still wrong, and it is
        # the list an estimator checks the £— against.
        _per_unit_price = method in ("subcontract_plating_named_spec",
                                     "subcontract_plating_historical_comparator",
                                     "estimator_stated_price",
                                     "inherited_estimator_decision")
        if _per_unit_price and (_contrib or _deferred):
            _all_members = sorted(set(_contrib) | set(_deferred))
            _base = str(pe.get("description") or "").split(" — plated members:")[0]
            pe["description"] = (
                f"{_base} — plated members: {', '.join(_all_members)} "
                f"(the whole weldment: this is a quoted price per stand, so the mass is not "
                f"an input and no member is excluded from it)")
            pe["_plating_members_costed"] = _all_members
            pe["_plating_members_deferred"] = []
        elif _contrib or _deferred:
            _base = str(pe.get("description") or "").split(" — plated members:")[0]
            _desc = f"{_base} — plated members: {', '.join(_contrib) or 'none'}"
            if _deferred:
                _desc += f" (excluded, own detail differs: {', '.join(_deferred)})"
            pe["description"] = _desc
        priced += 1
    return priced


def _sheet_catalogue_token(material: Any) -> Optional[str]:
    """The word to look this material up by in the parts catalogue, or None.

    ASKED OF THE MATERIAL, NOT OF A LIST OF MATERIALS. A token list here would be a second
    classifier beside costed_facts.is_other_sheet_material, and those two disagreeing about
    one part is the defect family this codebase keeps finding. So: is it costed in the Other
    Sheet block at all, and if so what is it CALLED -- the longest word in its own name that
    is not a size, a colour or a finish.

    Length floor of three because a two-letter fragment matches everything. Word boundaries
    are enforced on the results in Python; SQL LIKE cannot, so '%ABS%' would otherwise pull in
    every ABSORBER and ABSOLUTE in the catalogue.
    """
    text = str(material or "").upper().replace("_", " ")
    if not text.strip():
        return None
    try:
        import costed_facts as _cf
        if not _cf.is_other_sheet_material(text):
            return None
    except Exception:
        return None
    words = [w for w in re.findall(r"[A-Z]{3,}", text) if w not in _NOT_A_MATERIAL_WORD]
    if not words:
        return None
    # Longest wins: "CLEAR POLYCARBONATE" looks itself up as POLYCARBONATE, not POLY, so the
    # catalogue is not asked a question that also matches polypropylene and polystyrene.
    return max(words, key=len)


def _sheet_catalogue_probes(material: Any) -> List[Tuple[str, Optional[str]]]:
    """Every name the catalogue might hold this material under, most specific first.

    Each probe is (the word to search a description for, a word the row must ALSO contain
    or None). The material's own name is always first — a row that says MFMDF is not
    improved on. The synonyms below it exist because a purchasing system is written by
    buyers over years and the same board arrives as "Melamine Faced MDF" on one invoice
    and "MFMDF" on the next.

    The second word is the family guard. "MELAMINE" alone matches melamine-faced chipboard
    and melamine-faced MDF equally, and one rate answering two questions is the fault this
    codebase keeps finding.
    """
    _own = _sheet_catalogue_token(material)
    if not _own:
        return []
    out: List[Tuple[str, Optional[str]]] = [(_own, None)]
    _fam = str(material or "").upper().replace(" ", "").replace("_", "").replace("-", "")
    for _tok, _req in (getattr(config, "BOARD_CATALOGUE_SYNONYMS", {}) or {}).get(_fam, ()):
        if str(_tok).upper() != _own:
            out.append((str(_tok).upper(), str(_req).upper() if _req else None))
    return out


def _resolve_board_sheet_rate_gbp_per_m2(material: str, thickness_mm: Optional[float]) -> Optional[Dict[str, Any]]:
    """Live £/m² rate for a plastic sheet material (HIPS etc.) derived from the CURRENT
    UDEF catalogue, so it tracks price changes rather than a stale config table.

    Queries dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING for PLAIN stock HIPS sheets at the given
    thickness, parses 'L x W x Tmm' from the description, computes £/m² = System cost per
    ÷ sheet area for each, and returns the MEDIAN of the plain-stock rates. Premium items
    (printed / mirrored / flocked / vac-formed / gold / silver) and tiny offcuts are
    excluded so the rate reflects plain sheet stock, not finished graphics.

    Returns {rate_gbp_per_m2, sample_count, thickness_mm, basis} or None (never raises,
    never invents a price). Consistent with the tube resolver: real catalogue rows only.
    """
    # ANY SHEET PLASTIC OR BOARD, NOT ONE OF THEM.
    #
    # This read "if 'HIPS' not in material: return None", with a comment saying other boards
    # keep their existing path. Their existing path is an LLM market guess, and 11650-04 is
    # what that costs: four ABS/PETG panels the engine holds no rate for, priced at GBP
    # 175.01, 244.97 and 114.98 a sheet for the same nominal material, two BLOCKING invariants
    # (material_has_no_rate_in_this_engine, price_not_reproducible) and a handed pair that
    # cannot agree because the guess is keyed per gauge.
    #
    # The rate was in the customer's own purchasing system the whole time. Everything below --
    # the plain-stock filter, the dimension parse, the median, the outlier caps -- is material-
    # agnostic already. One `if` was the whole gate, and a rule that names a material is the
    # thing this engine is not supposed to contain.
    _probes = _sheet_catalogue_probes(material)
    if not _probes or thickness_mm is None:
        return None
    _token = _probes[0][0]
    try:
        _t_key = round(float(thickness_mm), 1)
    except (TypeError, ValueError):
        return None
    # KEYED ON MATERIAL AND GAUGE, NOT GAUGE ALONE. The cache held thickness only, which was
    # correct while exactly one material could reach it and silently wrong the moment a second
    # could: 2mm ABS would have been handed the 2mm HIPS rate, from a cache hit, with a basis
    # string naming the wrong material. One key for two questions.
    _cache_key = (_token, _t_key)
    if _cache_key in _SHEET_RATE_CACHE:
        _cached = _SHEET_RATE_CACHE[_cache_key]
        return None if _cached is None else {
            "rate_gbp_per_m2": _cached, "thickness_mm": _t_key, "material_token": _token,
            "sample_count": None, "basis": f"udef_{_token.lower()}_median_cached",
        }

    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        _SHEET_RATE_CACHE[_cache_key] = None
        return None
    # EVERY NAME THE CATALOGUE MIGHT HOLD IT UNDER, IN ORDER, AND THE FIRST ONE THAT
    # ANSWERS WINS. Never pooled: two spellings can be two different boards, and a median
    # across them would be one rate answering two questions.
    rates: List[float] = []
    _used, _needed = _token, None
    try:
        cur = cn.cursor()
        for _try_token, _require in _probes:
            # PARAMETERISED, not formatted in. The token comes from a material string read
            # off a drawing, and a drawing is external input like any other.
            cur.execute(
                """SELECT [Part code],[Description],[System cost per]
                   FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
                   WHERE [System cost per] > 0 AND [Description] LIKE ?""",
                (f"%{_try_token}%",),
            )
            _rows = cur.fetchall() or []
            if _require:
                _rows = [r for r in _rows
                         if _require in str(r[1] if len(r) > 1 else "").upper()]
            _r = _plain_stock_rates_gbp_per_m2(_rows, _try_token, _t_key)
            if _r:
                rates, _used, _needed = _r, _try_token, _require
                break
    except Exception:
        rates = []
    finally:
        try:
            cn.close()
        except Exception:
            pass

    if not rates:
        _SHEET_RATE_CACHE[_cache_key] = None
        return None
    import statistics as _stats
    _median = round(_stats.median(rates), 2)
    _SHEET_RATE_CACHE[_cache_key] = _median
    return {
        "rate_gbp_per_m2": _median,
        "thickness_mm": _t_key,
        "material_token": _used,
        "sample_count": len(rates),
        "basis": (f"udef_{_used.lower()}_median_live" if not _needed else
                  f"udef_{_used.lower()}_with_{_needed.lower()}_median_live"),
    }


# The rung of the length search that is a fallback, not a reading. Named once so the
# estimator, the invariant and the pre-flight all test for the same string.
SECTION_LENGTH_FALLBACK = "max_dimension_fallback"


def _infer_section_length_mm(part: Dict[str, Any]) -> Optional[float]:
    """How long the section is, and — on the part — WHERE that came from.

    THE LAST RUNG IS A FALLBACK AND IT WAS INDISTINGUISHABLE FROM A READING. Four real
    sources are tried, then the biggest number found anywhere on the part, and the function
    returned a bare float either way. So nothing downstream could say whether a leg's 1,397 mm
    was the cut length the LLM transcribed off the drawing (it was, on 7332-01-002:
    section_stock.length_mm, source llm_full_extract) or the page reader's summed cut path.

    Two stamps now travel with the number:
      _section_length_source  — the RUNG: section_stock / stated_length / developed_length /
                                overall_length / max_dimension_fallback / none
      _section_length_reader  — WHO read it: the section_stock's own source or detection
                                path (llm_full_extract, weldment_cut_list, canonical_profile,
                                inference ...), a field's _source sibling, or the
                                all_dimensions_mm list for the fallback.

    The fallback is still returned — a stand's height is usually a fair INDICATIVE length
    for its leg — and the CALLER decides whether it is priced, flagged, or refused.
    """
    _ss = part.get("section_stock") or {}
    _ss_len = _safe_float(_ss.get("length_mm"))
    if _ss_len is not None and _ss_len > 0:
        part["_section_length_source"] = "section_stock"
        part["_section_length_reader"] = str(
            _ss.get("source") or _ss.get("detection_path") or "section_stock")
        return _ss_len
    direct = _safe_float(part.get("length_mm"))
    if direct is not None and direct > 0:
        part["_section_length_source"] = "stated_length"
        part["_section_length_reader"] = str(
            part.get("length_mm_source") or part.get("geometry_source") or "stated_length")
        return direct
    geom = part.get("normalized_geometry", {}) or {}
    developed = _safe_float(geom.get("developed_length_mm"))
    if developed is not None and developed > 0:
        part["_section_length_source"] = "developed_length"
        part["_section_length_reader"] = str(
            geom.get("developed_length_mm_source") or geom.get("geometry_source")
            or part.get("geometry_source") or "normalized_geometry")
        return developed
    overall = _safe_float(part.get("overall_length_mm"))
    if overall is not None and overall > 0:
        part["_section_length_source"] = "overall_length"
        part["_section_length_reader"] = str(
            part.get("overall_length_mm_source") or part.get("geometry_source")
            or "overall_length")
        return overall
    dims = [_safe_float(v) for v in part.get("all_dimensions_mm", [])]
    dims = [v for v in dims if v is not None and v > 0]
    if dims:
        # NOT A READING. The largest dimension on a drawing is as likely to be the stand's
        # height, a GA overall, or the page reader's cut path as this part's cut length.
        part["_section_length_source"] = SECTION_LENGTH_FALLBACK
        part["_section_length_reader"] = "all_dimensions_mm"
        return max(dims)
    part["_section_length_source"] = "none"
    part["_section_length_reader"] = "none"
    return None


def _is_section_or_wire_candidate(part: Dict[str, Any], material: Optional[str]) -> bool:
    policy = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
    if not bool(policy.get("enabled", True)):
        return False
    if part.get("section_stock"):
        return True
    tokens = [str(t).upper() for t in policy.get("section_keywords", [])]
    blob = " ".join(
        [
            str(part.get("description") or ""),
            str(part.get("normalized_material") or ""),
            str(material or ""),
        ]
    ).upper()
    return any(token in blob for token in tokens)


def _resolve_labour_rate(operation: str) -> Dict[str, Any]:
    result = get_best_price(PriceRequest(kind="labour_rate", operation=operation))
    selected = _extract_selected_price(result)
    price = _selected_price_value(selected)
    unit = _selected_price_unit(selected)
    if price is None:
        return {"result": result, "applied_hourly_rate": None, "applied_basis": None}

    if is_per_hour_unit(unit):
        return {"result": result, "applied_hourly_rate": price, "applied_basis": "GBP_per_hour"}

    return {"result": result, "applied_hourly_rate": None, "applied_basis": None}


def _resolve_part_system_cost(part: Dict[str, Any]) -> Dict[str, Any]:
    part_number = str(part.get("part_number") or "").strip()
    item_number = str(part.get("item_number") or "").strip()
    part_code = part_number or item_number
    description = str(part.get("description") or "").strip()
    if not part_code and not description:
        return {"result": {}, "applied_unit_cost": None, "matched_part_code": None}

    candidate_codes: List[str] = []
    for code in [part_code, part_number, item_number]:
        code = str(code or "").strip()
        if not code:
            continue
        candidate_codes.extend(
            [
                code,
                code.replace(" - ", "-"),
                code.replace(" ", ""),
                code.upper(),
                code.replace(" - ", "-").upper(),
                code.replace(" ", "").upper(),
            ]
        )

    dedup_codes: List[str] = []
    seen_codes = set()
    for code in candidate_codes:
        key = code.upper()
        if key not in seen_codes:
            seen_codes.add(key)
            dedup_codes.append(code)

    best_result: Dict[str, Any] = {}
    best_price: Optional[float] = None
    matched_part_code: Optional[str] = None
    # A ZERO IS NOT A PRICE. IT IS THE ABSENCE OF ONE, AND IT ENDED THE SEARCH.
    #
    # UDEF holds catch-all rows — FIXING, and ~900 under MISC — priced £0.00. The legacy
    # connector's code-seek is `WHERE [Part code] = ?` with no positive-price filter, so a
    # line coded FIXING matched that row, came back at 0.0, and `price is not None` returned
    # it from here on the spot. Everything downstream was then unreachable for exactly the
    # lines that needed it most: the PricingService rungs (UDEF by description, historical
    # quotes, supplier catalogue, the market fallback) AND the standard-commodity provisional
    # at the bottom of this function, which is itself gated on `best_price is None`.
    #
    # That is why 12349-02's M4 flange button screw and 3.5x19 wood screw reached the
    # estimator as "MATERIAL UNPRICED: enter a unit rate" while the bumpon on the same BOM —
    # coded P/P, which has NO catch-all row — fell through to the market rung and priced at
    # 35p. One class word with a £0.00 row in the catalogue, and one without.
    #
    # So a zero no longer terminates the search; it is REMEMBERED and returned only if
    # nothing better is found, which keeps today's answer wherever today's answer was all
    # there was. Nothing is overwritten by a worse figure: every later rung returns only a
    # price greater than zero.
    zero_result: Dict[str, Any] = {}
    zero_code: Optional[str] = None

    for code in dedup_codes or [""]:
        result = get_best_price(
            PriceRequest(
                kind="part_system_cost",
                part_code=code,
                description=description,
            )
        )
        selected = _extract_selected_price(result)
        price = _selected_price_value(selected)
        if price is not None and price > 0:
            return {"result": result, "applied_unit_cost": price, "matched_part_code": code}
        if price is not None and not zero_result:
            zero_result, zero_code = result, code
        if not best_result:
            best_result = result
            matched_part_code = code

    # FALLBACK: the legacy connector found no price. Try the newer PricingService
    # chain (UDEF + historical-quote RAG + supplier catalogue + LLM), which finds
    # bought-in items the legacy UDEF-only connector misses (e.g. the loom at
    # £24.15 from historical_quote_material_line). This is what stops identified
    # bought-in items landing at the £0.42 handling floor. Additive and guarded:
    # if PricingService is unavailable or returns nothing usable, behaviour is
    # unchanged from before.
    ps = _get_pricing_service()
    if ps is not None:
        try:
            # THE WHOLE PART, NOT A STUB. This used to hand over three keys — number,
            # description, material — and the fallback gate on the other side reads
            # is_assembly_parent, is_sub_assembly, reliability_flags and the operations to
            # decide whether asking a market price even makes sense. None of them were
            # present, so every guard but the two text tests was blind, and 12120-01-101 and
            # -103 — weldments we fabricate, whose material is carried by their children —
            # were sent to an LLM to be priced as if they were catalogue items. An LLM cannot
            # know what an in-house code costs, and it answered anyway.
            anchor = ps._select_anchor_price_source(
                {
                    **{k: v for k, v in part.items() if k != "part_number"},
                    "part_number": part_code,
                    "description": description,
                    "normalized_material": part.get("normalized_material"),
                }
            )
            ps_price = _safe_float(anchor.get("unit_price_gbp")) if anchor else None
            if ps_price is not None and ps_price > 0:
                if (anchor or {}).get("item_priced"):
                    part.setdefault("review_flags", []).append(
                        f"AI researched price £{ps_price:,.2f}: priced as "
                        f"{anchor['item_priced']}")
                return {
                    "result": {
                        "selected": {
                            "source": anchor.get("source"),
                            "price": ps_price,
                            "confidence": anchor.get("confidence"),
                            "provenance": anchor.get("provenance"),
                            "review_required": anchor.get("review_required",
                                                         anchor.get("review_flag", False)),
                            "review_reason": anchor.get("review_reason"),
                            # The anchor already knows what it is — a UDEF row, a historical
                            # quote line, or a web/AI estimate. Dropping that here is what
                            # left an LLM price indistinguishable from a catalogue hit by the
                            # time it reached the sheet.
                            "metadata": {
                                "pricing_mode": anchor.get("source_type") or anchor.get("source"),
                                "llm_provider": anchor.get("llm_provider"),
                                "supplier_name": anchor.get("supplier_name"),
                                "price_date": anchor.get("price_date"),
                                "review_reason": anchor.get("review_reason"),
                                "item_priced": anchor.get("item_priced"),
                            },
                            "evidence": {
                                "web_query": anchor.get("web_query"),
                                "low_estimate_gbp": anchor.get("low_estimate_gbp"),
                                "high_estimate_gbp": anchor.get("high_estimate_gbp"),
                                "source_note": anchor.get("provenance"),
                            },
                        }
                    },
                    "applied_unit_cost": ps_price,
                    "matched_part_code": part_code,
                }
        except Exception:
            pass

    # DB-FREE STANDARD-COMMODITY PROVISIONAL — the reproducible last resort.
    #
    # Everything above needs the DB (the legacy connector and the PricingService rungs). When
    # none of it found a price — the DB was unreachable, PricingService could not be built, a
    # rung threw and was swallowed, or the class-word code ('STD PART') left nothing to look up
    # — a generically-named standard commodity was still handed £0, even though config carries a
    # fixed figure for it. 11762-17's PERFO PLASTIC LOCKING CLIP is exactly that: no SDI code, a
    # class word in the code column, and £1.20 sitting in STANDARD_COMMODITY_PRICE_GBP that the
    # only route to it (inside PricingService's web/AI fallback) could not reach here.
    #
    # Consulted LAST, so a real catalogue/UDEF/history rate still wins; keyed on the DESCRIPTION,
    # so a class-word code is no obstacle; DB-free, so it is reproducible on any box. Non-firm and
    # flagged for review — a provisional, not a quote.
    if best_price is None:
        try:
            from pricing_service import standard_commodity_price as _std_commodity
            _com = _std_commodity(part)
        except Exception:                                        # noqa: BLE001
            _com = None
        _com_price = _safe_float(_com.get("unit_price_gbp")) if _com else None
        if _com_price is not None and _com_price > 0:
            return {
                "result": {"selected": {
                    "source": _com.get("source"),
                    "price": _com_price,
                    "confidence": _com.get("confidence"),
                    "provenance": _com.get("provenance"),
                    "review_required": _com.get("review_flag", True),
                    "review_reason": _com.get("review_reason"),
                    "metadata": {
                        # standard_commodity_price sets source_type and source to the same value,
                        # so one read is enough — and avoids a hand-rolled name fallback chain.
                        "pricing_mode": _com.get("source_type"),
                        "supplier_name": _com.get("supplier_name"),
                    },
                }},
                "applied_unit_cost": _com_price,
                # Matched on the description, not a code — say so rather than claim a code hit.
                "matched_part_code": None,
            }

    # ── RUNG 4: A RESEARCHED PRICE, WITH ITS EVIDENCE ─────────────────────────────────
    #
    # The commodity table above is empty now (D-095): every figure in it was somebody
    # working a number out once and typing it into the source. This is what replaces it —
    # and the difference is not the label, because that table called itself INDICATIVE too.
    # The difference is that what comes back from here can be CHECKED: it names its source,
    # the date it was true, what it is per, the quantity it was found at, and the
    # arithmetic from that figure to the money on this line.
    #
    # If the research cannot produce all of that, NOTHING is returned. The line stays
    # unpriced, the release gate refuses to publish, and the workbook says which source
    # would have answered it. That is the whole contract: a price or a named gap, never a
    # zero and never a figure nobody can check.
    if best_price is None:
        try:
            from indicative_price import resolve_indicative as _rung4

            _researcher = _rung4_researcher
            # ── ONE WORD IS NOT A PURCHASE ──────────────────────────────────────
            #
            # James Gray, 22 Sep 2026: "we need to be able to price castors and hinges."
            # On the first concept book both sat at £0, and the reason was in the brief:
            # this rung asks the market to name a REAL CURRENT LISTING, and it was being
            # handed the single word CASTOR — no diameter, no fixing, no load. Nothing
            # usable can come back from that, and nothing did.
            #
            # A render answers more than one word: a wheel about 75mm, black, on a plated
            # bracket. `research_description` carries exactly that, written by the reader
            # that saw it and marked as approximate and sighted in its own text, so the
            # answer is a price for a standard item of that description rather than a
            # confident figure for a code nobody has. The description on the sheet does
            # not change; only the question asked of the market does.
            _sighted_desc = str(part.get("research_description") or "").strip()
            _ind = _rung4(
                # NO CODE ON A SIGHTED LINE. The code is one this engine minted from a
                # render; putting it in the brief invites an answer about a part number
                # no supplier has ever listed.
                {"code": "" if _sighted_desc else part.get("part_number"),
                 # AND WHAT THE PACK SAYS THIS IS, where its own words are only a code.
                 "description": (
                     _sighted_desc or " — ".join(
                         x for x in (str(part.get("description") or "").strip(),
                                     str(part.get("research_context") or "").strip()) if x)),
                 "quantity": part.get("quantity"),
                 # A LINE'S OWN UNIT, WHICH THE BRIEF NEVER USED TO SEE. The edging stub
                 # carries `unit_of_measure = "m"` and this dict did not pass it on, so the
                 # brief asked for a price "per each" on a material sold by the metre —
                 # a fact recorded under one name and read under another, again.
                 "unit_of_measure": part.get("unit_of_measure"),
                 "mass_kg": part.get("normalized_weight_kg"),
                 # THE ORIGIN IS THE TRUE ONE, so the guard judges the brief on what it
                 # actually is. A sighted description is not a drawing's reading and must
                 # not travel as one.
                 "input_origins": dict(part.get("input_origins") or {},
                                       **({"description": "vision_concept_sighted"}
                                          if _sighted_desc else {}))},
                order_qty=int(_safe_float(part.get("job_quantity")) or 1),
                as_of=str(part.get("run_date") or ""),
                ask=_researcher,
            )
        except Exception:                                        # noqa: BLE001
            _ind = {}
        _ind_price = _safe_float((_ind or {}).get("price_gbp"))
        if _ind_price is not None and _ind_price > 0:
            # WHAT WAS ACTUALLY PRICED, on the line. £126.04 for "a screw" is obviously wrong
            # only once somebody can see the model priced something else; said here, it is
            # visible before anyone reaches the total.
            if (_ind or {}).get("item_priced"):
                part.setdefault("review_flags", []).append(
                    f"AI researched price £{_ind_price:,.2f}: priced as "
                    f"{_ind['item_priced']}")
            return {
                "result": {"selected": {
                    "source": (_ind.get("evidence") or {}).get("source"),
                    "price": _ind_price,
                    "review_required": True,
                    "review_reason": _ind.get("status"),
                    # THE STAMP THE WITHHOLDING RULE READS. price_provenance.
                    # stamp_is_reproducible looks for this key on the block or one level
                    # inside it; without it every researched figure read as a guess that
                    # moves, and was kept off the price column however stable it was.
                    "price_is_reproducible": bool(_ind.get("price_is_reproducible")),
                    "metadata": {
                        "pricing_mode": "llm_indicative",
                        "evidence": _ind.get("evidence"),
                        "calculation": _ind.get("calculation"),
                        "label": _ind.get("label"),
                        "price_first_taken": _ind.get("price_first_taken"),
                        "item_priced": _ind.get("item_priced"),
                    },
                }},
                "applied_unit_cost": _ind_price,
                "matched_part_code": None,
            }
        # Not priced, and WHY is worth keeping: it is what the workbook shows instead of a
        # number, and what tells an estimator which source to go and get.
        if _ind and _ind.get("missing"):
            part.setdefault("review_flags", []).append(
                f"{part.get('part_number') or part.get('description') or 'this line'}: "
                f"NOT PRICED — {_ind['missing']}")

    # The remembered zero, if that is genuinely all the catalogue had to say. Returned with
    # its own result and code so the line reads exactly as it did before this rung learned
    # to keep looking.
    if best_price is None and zero_result:
        return {"result": zero_result, "applied_unit_cost": 0.0,
                "matched_part_code": zero_code}

    return {"result": best_result, "applied_unit_cost": best_price, "matched_part_code": matched_part_code}


_MEASURED_BEND_SOURCES = {"solidworks_api", "solidworks", "native", "dxf_flat_pattern", "dxf",
                          # The BENDLINES layer itself — the narrowest and strongest of them.
                          "dxf_bendlines_layer",
                          # fold_count's own names for the same two measured things.
                          "flat_pattern_bend_lines", "solidworks_bend_features"}


def _model_measured_zero_bends(part: Dict[str, Any]) -> bool:
    """Did something that can actually SEE the part count its bends, and find none?

    THE ENGINE'S OWN RULE, BROKEN IN ONE LINE. bend_count = 0 stamped by solidworks_api is a
    measurement — the model was read and it has no bends. Two places treated it as absence:

        bends = manufacturing_features.get("bend_count") or max(len(angles_deg), ...)

    A zero is falsy, so the fold fell through to the drawing's own callouts, and 12120's 04M
    came back as one bend from a 30-degree angle on the PDF. That is why the plate gate kept
    removing the op and the sheet kept charging for it: the op was stripped, and the evidence
    that regenerates it was left on the record.

    Falling through IS right when the zero came from something that cannot see bends — that
    is the fold-shadowing fix, and parts whose folds live only in a PDF callout still need it.
    So the distinction is not "is it zero" but "did anything actually look".
    """
    if not isinstance(part, dict):
        return False
    if part.get("native_flat_solid"):
        return True          # the solid is one thickness thick — nowhere for a bend to be
    mf = part.get("manufacturing_features") or {}
    if not isinstance(mf, dict):
        return False
    count = mf.get("bend_count")
    if count is None or _safe_int(count):
        return False         # absent, or a real count — neither is a measured zero
    return str(mf.get("bend_count_source") or "").strip().lower() in _MEASURED_BEND_SOURCES


def _bends_for_coating(part: Dict[str, Any]) -> Tuple[int, str]:
    """How many bend-edge strips the powder is spread over, and on whose authority.

    THE FOLD LABOUR OBEYS THE DXF AND THE COATING AREA DID NOT. The route charges the
    measured count -- `manufacturing_features.bend_count`, which IS the BENDLINES figure
    when a flat pattern answered -- but both coating-area calculations took

        max(mf.bend_count, geometry_rollup.estimated_bend_line_count, fold_count_textual)

    so a drawing note or a dashed-line heuristic could outvote the press brake's own layer.
    Measured on a probe of 401912-02's divider: a DXF that measured ONE bend, against three
    angle callouts, coats 0.4137 m2 instead of 0.3566 m2 -- 16% more area, on a part where
    powder is about sixty per cent of the unit cost. It is not a rounding difference and it
    moves money in the direction nobody checks, because a slightly high coating figure reads
    as caution rather than as an error.

    The max() is right where nothing measured: a rollup count and a drawing's callouts are
    the only evidence there is, and the larger is the safer bet for a consumable. It is
    wrong the moment something has actually looked. So: a measured count controls, and
    everything else keeps the behaviour it had.
    """
    def _nz(val: Any) -> int:
        n = _safe_int(val)
        return int(n) if n is not None else 0

    mf = part.get("manufacturing_features") or {}
    _src = str(mf.get("bend_count_source") or "").strip().lower()
    if _src in _MEASURED_BEND_SOURCES:
        return _nz(mf.get("bend_count")), _src
    return max(_nz(mf.get("bend_count")),
               _nz((part.get("geometry_rollup") or {}).get("estimated_bend_line_count")),
               _nz(part.get("fold_count_textual"))), (_src or "unmeasured_proxies")


def _dxf_geometry_trusted(part: Dict[str, Any], ng: Dict[str, Any]) -> bool:
    """True when blank/bbox extents came from flat DXF, not PDF page vectors."""
    if part.get("dxf_augmented") or part.get("flat_pattern_detected"):
        return True
    if part.get("geometry_source") == "dxf_flat_pattern":
        return True
    if _has_native_flat(part):
        return True
    if str(ng.get("geometry_source") or "").lower() in {
            "dxf_flat_pattern", "dxf", "solidworks_flat_pattern"}:
        return True
    prov = part.get("provenance") or {}
    if str(prov.get("source") or "").lower() == "dxf":
        return True
    return False


def _plausible_blank_dimension_mm(value: Optional[float], measured: bool = False) -> bool:
    """Could this number be one side of a blank?

    A GUARD AGAINST MISREAD TEXT, APPLIED TO A MEASUREMENT, THROWS AWAY THE MEASUREMENT.

    Both rules below exist for text. Dates parse as dimensions -- "07/04/2021" arrives as
    2021.0mm -- so anything in the 1900-2100 band was refused, and 2500 capped a number
    picked out of a drawing by OCR. Neither risk exists for a DXF flat pattern: that value
    is the extent of a closed profile in a CAD file, not a string somebody's reader had a
    go at. Applying the text rules to it cost real parts:

      * a 2000mm panel -- one of the commonest shopfitting heights there is -- was
        discarded as a calendar year
      * anything over 2500mm was discarded outright, on a machine whose standard sheet is
        3050 long, so a part that plainly can be cut was refused as impossible

    In both cases the part then carried no blank, priced no material, and said nothing.

    So `measured` splits them. Text keeps both rules, because a misread there is likely and
    a wrong blank is worse than none. A measurement keeps only the physical bound -- how big
    a sheet part can be at all, which blank_credibility already answers, rather than a second
    number in a second module meaning the same thing.
    """
    if value is None or value <= 0:
        return False
    policy = getattr(config, "BLANK_DIMENSION_POLICY", {}) or {}
    min_mm = float(policy.get("min_single_dim_mm", 1.0))
    if measured:
        try:
            import blank_credibility as _bc
            max_mm = float(_bc.MAX_SHEET_PART_MM)
        except Exception:                                    # noqa: BLE001
            max_mm = 4000.0
        return min_mm <= value <= max_mm
    # Reject calendar years misread as dimensions.
    # Dates like "07/04/2021" get parsed as 2021.0mm — filter them out.
    if 1900.0 <= value <= 2100.0:
        return False
    max_mm = float(policy.get("max_single_dim_mm", 2500.0))
    return min_mm <= value <= max_mm


# Tolerance table sequence that appears on EVERY drawing border — NOT a part thickness.
_TOLERANCE_TABLE_SEQUENCE = {0.5, 1.0, 1.5, 2.0, 3.0}


def _safe_thickness_mm(part: Dict[str, Any]) -> Optional[float]:
    """
    Pick the first plausible thickness from the part.

    Priority order (most reliable first):
      1. DXF filename thickness — "part_2mm_PETG.DXF" -> 2.0  (MOST RELIABLE
         for flat parts; the fabricator names the file by stock thickness)
      2. normalized_thickness_mm (already resolved upstream)
      3. thicknesses_mm list, stripping tolerance-table boilerplate

    Rejects: year-like values (1900-2100), values <= 0, values outside 0.3-50mm.
    Returns None if no reliable thickness found.
    """
    # MATERIAL-AWARE FLOOR. A sheet-metal gauge of 0.5mm is ordinary; a 0.5mm timber panel
    # is not a thing. Board and timber stock starts around 3mm (hardboard/thin ply) and is
    # usually 6-25mm, so anything below that on a joinery part is the tolerance table
    # bleeding in, not a thickness. It reached the sheet as "0.5mm TIMBER" on the Horti
    # Crate. Reject it and return nothing: an absent thickness is visibly missing, whereas
    # a wrong one silently drives grouping, gauge pricing and any thickness-based timing.
    _mat_thk_u = " ".join([
        str(part.get("normalized_material") or ""),
        str(part.get("material") or ""),
    ]).upper()
    # Two floors, because the stock differs. Sheet board is made thin — 3mm MDF and 3mm ply
    # are stocked items — but solid timber is not: nobody machines a 3mm pine panel, and the
    # thinnest practical section is around 6mm. One floor would either let solid-timber noise
    # through or reject real thin board. Sheet goods are checked first so a veneered or
    # ply-faced product ("OAK VENEER MDF", "BIRCH PLY") takes the board floor, not the
    # timber one — it is a board, whatever species is on its face.
    # ONE DEFINITION, IN config. This list lived here and three other modules had their own,
    # and the faced family was missing from most of them at one time or another.
    _SHEET_BOARD_TOKENS = tuple(getattr(config, "SHEET_BOARD_TOKENS", ()))
    _SOLID_TIMBER_TOKENS = tuple(getattr(config, "SOLID_TIMBER_TOKENS", ()))
    # MELAMINE-FACED BOARD IS BOARD. The token list is what decides the floor AND the
    # ceiling below, so a substrate missing from it is silently treated as sheet metal —
    # which is how 12422-24's MFC panel came to be measured against a 25mm gauge bound.
    _SHEET_BOARD_TOKENS = _SHEET_BOARD_TOKENS + tuple(
        getattr(config, "FACED_BOARD_TOKENS", ()))
    _is_board_thk = any(t in _mat_thk_u for t in _SHEET_BOARD_TOKENS)
    _is_timber_thk = any(t in _mat_thk_u for t in _SOLID_TIMBER_TOKENS)
    if _is_board_thk:
        _min_t = float(getattr(config, "MIN_BOARD_THICKNESS_MM", 3.0))
    elif _is_timber_thk:
        _min_t = float(getattr(config, "MIN_SOLID_TIMBER_THICKNESS_MM", 6.0))
    else:
        _min_t = 0.0

    # AND THE CEILING DEPENDS ON THE SAME QUESTION. A hard 25.0 is generous for sheet metal
    # and wrong for board: shop-fitting board runs 18/22/25/28/30 and beyond. drawing_job_merge
    # already widened its filename bound for board, so a "28MM_MFC" DXF name was read there
    # and thrown away here — the panel kept whatever weaker figure the drawing text gave it.
    # Both modules now read config.MAX_BOARD_THICKNESS_MM.
    _max_t_for_part = float(getattr(
        config,
        "MAX_BOARD_THICKNESS_MM" if (_is_board_thk or _is_timber_thk)
        else "MAX_SHEET_THICKNESS_MM",
        75.0 if (_is_board_thk or _is_timber_thk) else 25.0))

    def _ok(v: Optional[float]) -> bool:
        if v is None or v <= 0:
            return False
        if _min_t and v < _min_t:
            part.setdefault("review_flags", []).append(
                f"thickness {v:g}mm rejected: below the {_min_t:g}mm minimum for a "
                f"board/timber part — that is tolerance-table text, not a stock thickness. "
                f"Thickness left unset; confirm the board gauge from the drawing")
            return False
        return True

    _dfn = str(part.get("dxf_source_file") or part.get("geometry_source_path") or "")
    if _dfn:
        _tm = re.search(r"[_\-\s](\d+\.?\d*)\s*mm", _dfn, re.IGNORECASE)
        if _tm:
            _tv = _safe_float(_tm.group(1))
            if _tv and 0.3 <= _tv <= _max_t_for_part and _ok(_tv):
                return _tv

    # Already-normalised thickness — skip tolerance-table noise when DXF exists
    raw = part.get("normalized_thickness_mm")
    if raw:
        v = _safe_float(raw)
        _max_t = _max_t_for_part
        if v and 0.4 <= v <= _max_t and not (1900 <= v <= 2100) and _ok(v):
            if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE or not _dfn:
                return v

    # thicknesses_mm list with tolerance-table stripping
    _max_t = _max_t_for_part
    candidates = [_safe_float(x) for x in part.get("thicknesses_mm", [])]
    # A6: reject implausible sheet thickness (e.g. a 500mm dimension misparsed as gauge)
    candidates = [v for v in candidates
                  if v and 0.3 <= v <= _max_t and not (1900 <= v <= 2100)]
    if not candidates:
        return None

    # Tolerance-table strip runs FIRST, on the unfiltered set. The board floor below would
    # otherwise remove 0.5/1.0/1.5/2.0 itself, break this subset test, and leave the 3.0
    # that is also part of the table looking like a real 3mm board.
    cand_set = set(round(v, 1) for v in candidates)
    if _TOLERANCE_TABLE_SEQUENCE.issubset(cand_set):
        stripped = [v for v in candidates if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE]
        # Only use the stripped list if something survives; otherwise the
        # original values ARE the real thickness (e.g. a 2mm-only acrylic part).
        if stripped:
            candidates = stripped
        elif _min_t:
            # Board/timber part whose ONLY thickness candidates are the tolerance table.
            # For metal the fall-back above is sound (0.5-3mm are real gauges), but no
            # board is made in those sizes, so there is nothing here to keep. Return
            # nothing rather than the 3.0 that happens to sit at the top of the table.
            part.setdefault("review_flags", []).append(
                "no board thickness on the drawing - the only values found were the "
                "tolerance table. Thickness left unset; confirm the board gauge")
            return None
    if not candidates:
        return None

    # Material-aware floor, applied after the table strip.
    candidates = [v for v in candidates if _ok(v)]
    if not candidates:
        return None

    from collections import Counter
    rounded = [round(v, 2) for v in candidates]
    _best = Counter(rounded).most_common(1)[0][0]
    return _best or None


def _title_block_blank_mm(part: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Drawing flat-pattern or L×W callout — preferred over inflated DXF bbox."""
    fp = part.get("flat_pattern_dimensions_mm") or []
    if len(fp) >= 2:
        a, b = _safe_float(fp[0]), _safe_float(fp[1])
        if a and b and _plausible_blank_dimension_mm(a) and _plausible_blank_dimension_mm(b):
            return max(a, b), min(a, b)
    dims = sorted(
        {
            v
            for v in (_safe_float(x) for x in (part.get("all_dimensions_mm") or []))
            if v is not None and _plausible_blank_dimension_mm(v) and v <= 800.0
        },
        reverse=True,
    )
    best_area: Optional[float] = None
    best_pair: Tuple[Optional[float], Optional[float]] = (None, None)
    for i, a in enumerate(dims):
        for b in dims[i + 1 :]:
            area = a * b
            if area < 5_000.0:
                continue
            if best_area is None or area < best_area:
                best_area = area
                best_pair = (max(a, b), min(a, b))
    if best_pair[0] and best_pair[1]:
        return best_pair
    blob = " ".join(
        [
            str(part.get("description") or ""),
            " ".join(str(x) for x in (part.get("all_dimensions_mm") or [])),
            str(part.get("purchased_size") or ""),
        ]
    )
    m = re.search(
        r"(\d{2,4}(?:\.\d+)?)\s*[xX×]\s*(\d{2,4}(?:\.\d+)?)\s*(?:mm)?",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        a, b = _safe_float(m.group(1)), _safe_float(m.group(2))
        if a and b and _plausible_blank_dimension_mm(a) and _plausible_blank_dimension_mm(b):
            return max(a, b), min(a, b)
    g03_l = _safe_float(part.get("blank_length_mm"))
    g03_w = _safe_float(part.get("blank_width_mm"))
    if g03_l and g03_w and _plausible_blank_dimension_mm(g03_l) and _plausible_blank_dimension_mm(g03_w):
        return max(g03_l, g03_w), min(g03_l, g03_w)
    ol = _safe_float(part.get("overall_length_mm"))
    ow = _safe_float(part.get("overall_width_mm"))
    if ol and ow and _plausible_blank_dimension_mm(ol) and _plausible_blank_dimension_mm(ow):
        if ol <= 700.0 and ow <= 700.0:
            return max(ol, ow), min(ol, ow)
    return None, None


def infer_primary_dimensions(part: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Infer blank dimensions in priority order:
      1. DXF flat-pattern exact geometry  (blank_length_mm / blank_width_mm)
      2. DXF bounding box  (normalized_geometry bbox — not PDF page vectors)
      3. part.overall_length_mm / overall_width_mm  (drawing_job_merge / OCR)
      4. part.all_dimensions_mm  (dimension text from drawing)
    PDF estimated_cut_length is never used for blank size — it sums all page vectors.
    """
    ng = part.get("normalized_geometry") or {}
    if not isinstance(ng, dict):
        ng = {}

    # ── Priority 1: DXF exact flat-pattern ────────────────────────────────────
    dxf_l = _safe_float(ng.get("blank_length_mm"))
    dxf_w = _safe_float(ng.get("blank_width_mm"))
    # A MEASUREMENT THROWN AWAY MUST NOT GO QUIETLY. When a flat pattern exists and is
    # refused, the part falls through to weaker evidence or to nothing at all -- and a part
    # with no blank prices no material, which reads on the sheet as a part that is free to
    # make. That is the same silent zero the door cost, arriving by a different door.
    if dxf_l and dxf_w and not (_plausible_blank_dimension_mm(dxf_l, measured=True)
                                and _plausible_blank_dimension_mm(dxf_w, measured=True)):
        _why = "; ".join(
            f"{_v:g}mm is outside what a sheet part can be" for _v in (dxf_l, dxf_w)
            if not _plausible_blank_dimension_mm(_v, measured=True))
        _flags = part.setdefault("review_flags", [])
        _detail = (f"The flat pattern reads {dxf_l:g} x {dxf_w:g} mm and was refused: "
                   f"{_why}. This part now has no measured blank, so its material is "
                   f"costed from weaker evidence or not at all. Either the DXF is not a "
                   f"flat pattern, or this part is bigger than anything this engine will "
                   f"nest.")
        if not any(isinstance(f, dict) and f.get("flag") == "measured_blank_refused"
                   for f in _flags):
            _flags.append({"severity": "warning", "flag": "measured_blank_refused",
                           "detail": _detail})
    if dxf_l and dxf_w and _plausible_blank_dimension_mm(dxf_l, measured=True) \
            and _plausible_blank_dimension_mm(dxf_w, measured=True):
        # Only second-guess DXF when a side is implausibly large (e.g. whole-page bbox).
        # Normal flats (500 mm base ~565×542) must keep DXF blank — £/tonne clamp fixes material.
        if max(dxf_l, dxf_w) > 900.0 or min(dxf_l, dxf_w) > 700.0:
            tb_l, tb_w = _title_block_blank_mm(part)
            if tb_l and tb_w:
                dxf_area = dxf_l * dxf_w
                tb_area = tb_l * tb_w
                if dxf_area > 2.5 * tb_area and tb_area >= 10_000.0:
                    return {
                        "overall_length_mm": tb_l,
                        "overall_width_mm": tb_w,
                        "all_dimensions_mm": sorted([tb_l, tb_w], reverse=True),
                        "source": "title_block_preferred_over_inflated_dxf_blank",
                    }
        return {
            "overall_length_mm": dxf_l,
            "overall_width_mm": dxf_w,
            "all_dimensions_mm": sorted([dxf_l, dxf_w], reverse=True),
            # Report the flat pattern's ACTUAL source. Both are measured blanks, but a
            # modelled cut-list flat must not be reported to an estimator as a DXF.
            "source": ("solidworks_flat_pattern" if _has_native_flat(part)
                       else "dxf_flat_pattern"),
        }

    # ── Priority 2: DXF normalised geometry bounding box only ─────────────────
    if _dxf_geometry_trusted(part, ng):
        flat_box = ng.get("bounding_box_flat_mm", {}) if isinstance(ng, dict) else {}
        flat_length = _safe_float(flat_box.get("length"))
        flat_width = _safe_float(flat_box.get("width"))
        if (
            flat_length and flat_width
            and _plausible_blank_dimension_mm(flat_length, measured=True)
            and _plausible_blank_dimension_mm(flat_width, measured=True)
        ):
            return {
                "overall_length_mm": flat_length,
                "overall_width_mm": flat_width,
                "all_dimensions_mm": sorted([flat_length, flat_width], reverse=True),
                "source": "normalized_geometry_bbox",
            }

    # ── Priority 2b: G03 page-text blanks from document_builder ─────────────
    g03_l = _safe_float(part.get("blank_length_mm"))
    g03_w = _safe_float(part.get("blank_width_mm"))
    if (
        g03_l
        and g03_w
        and _plausible_blank_dimension_mm(g03_l)
        and _plausible_blank_dimension_mm(g03_w)
    ):
        return {
            "overall_length_mm": g03_l,
            "overall_width_mm": g03_w,
            "all_dimensions_mm": sorted([g03_l, g03_w], reverse=True),
            "source": "document_builder_g03",
        }

    # ── Priority 3: overall dimensions (merge / title block / OCR pick) ───────
    overall_length = _safe_float(part.get("overall_length_mm"))
    overall_width = _safe_float(part.get("overall_width_mm"))
    if (
        overall_length and overall_width
        and _plausible_blank_dimension_mm(overall_length)
        and _plausible_blank_dimension_mm(overall_width)
    ):
        return {
            "overall_length_mm": overall_length,
            "overall_width_mm": overall_width,
            "all_dimensions_mm": sorted([overall_length, overall_width], reverse=True),
            "source": "part_overall_dims",
        }

    # ── Priority 4: OCR / extracted dimension list ────────────────────────────
    dims = sorted(
        [
            v for v in (
                _safe_float(x) for x in part.get("all_dimensions_mm", [])
            )
            if v is not None and _plausible_blank_dimension_mm(v)
        ],
        reverse=True,
    )
    overall_length = overall_length if _plausible_blank_dimension_mm(overall_length) else None
    overall_width = overall_width if _plausible_blank_dimension_mm(overall_width) else None
    overall_length = overall_length or (dims[0] if dims else None)
    overall_width = overall_width or (dims[1] if len(dims) > 1 else None)
    return {
        "overall_length_mm": overall_length,
        "overall_width_mm": overall_width,
        "all_dimensions_mm": dims,
        "source": "ocr_dimensions" if len(dims) >= 2 else "no_dims_available",
    }


def _part_powder_text_blob(part: Dict[str, Any]) -> str:
    bits = [
        str(part.get("description") or ""),
        ";".join(str(x) for x in (part.get("process_notes") or [])),
        ";".join(str(x) for x in (part.get("surface_finishes") or [])),
        ";".join(str(x) for x in (part.get("colours") or [])),
    ]
    return " ".join(bits).upper()


def _effective_coated_faces_multiplier(part: Dict[str, Any]) -> Tuple[float, str]:
    """2.0 = both blank faces; reduced when SINGLE FACE / EXTERNAL ONLY etc. match description or notes."""
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    blob = _part_powder_text_blob(part)
    default_m = float(policy.get("coated_faces_multiplier", 2.0))
    for kw in policy.get("single_face_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("coated_faces_multiplier_single_face", 1.0)), "single_face_keyword"
    for kw in policy.get("partial_exterior_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("coated_faces_multiplier_partial_exterior", 1.3)), "partial_exterior_keyword"
    return default_m, "default_both_faces"


def _resolve_powder_material_price_per_kg(part: Dict[str, Any]) -> Tuple[float, str]:
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    blob = _part_powder_text_blob(part)
    for kw in policy.get("special_finish_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("powder_material_gbp_per_kg_special") or 0.0), "special_finish"
    return float(policy.get("powder_material_gbp_per_kg") or 0.0), "standard"


def _powder_coated_area_m2(
    part: Dict[str, Any],
    blank_length: Optional[float],
    blank_width: Optional[float],
) -> Tuple[float, Dict[str, Any]]:
    """
    Total coated surface for powder (flat faces + bend-edge strips).
    Flat area uses coated_faces_multiplier (default 2 = both sides of blank).
    """
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    if blank_length is None or blank_width is None or blank_length <= 0 or blank_width <= 0:
        return 0.0, {}
    L, W = float(blank_length), float(blank_width)
    faces_m, faces_reason = _effective_coated_faces_multiplier(part)
    flat_m2 = (L * W) / 1_000_000.0 * faces_m
    strip_mm = float(policy.get("bend_coating_strip_mm", 40.0))
    bends, bends_from = _bends_for_coating(part)
    fold_vals = part.get("fold_values_mm") or []
    perimeter_fold_mm = sum(_safe_float(x) or 0.0 for x in fold_vals)
    if perimeter_fold_mm > 0:
        bend_extra_m2 = (perimeter_fold_mm / 1000.0) * (strip_mm / 1000.0) * 2.0
    else:
        bend_extra_m2 = float(bends) * (strip_mm / 1000.0) * (min(L, W) / 1000.0) * 2.0
    total = flat_m2 + bend_extra_m2
    detail = {
        "flat_coated_m2": round(flat_m2, 4),
        "bend_extra_coated_m2": round(bend_extra_m2, 4),
        "bend_lines_used": bends,
        # Who supplied the count the strips were spread over. A coating area is one of the
        # few figures an estimator cannot check by eye, so it says where its inputs came from.
        "bend_lines_source": bends_from,
        "coated_faces_multiplier": faces_m,
        "coated_faces_reason": faces_reason,
    }
    return total, detail


def _rung4_researcher(_brief: Dict[str, Any]) -> Dict[str, Any]:
    """The engine's own web/LLM rung, behind the producer's seam.

    ONE RESEARCHER, NOT ONE PER CALLER. It was a closure inside the bought-in price chain,
    which is where it was first needed; a board is not a bought-in and would have got a
    second copy of it, and two copies of a price source is how two answers to one question
    start. Everything it does is material-agnostic already.
    """
    # THE POLICY SWITCH MEANS WHAT IT SAYS, FROM EVERY CALLER. `enable_web_ai_fallback` is
    # how the office turns the researched rung off — for a run that must not reach outside,
    # or while a provider is misbehaving — and a caller that ignores it makes the switch a
    # lie. The bought-in chain honoured it upstream; the board path reaches this function
    # directly, so the check belongs here, where both arrive.
    if not (getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}).get(
            "enable_web_ai_fallback", True):
        return {}
    from web_ai_price_lookup import lookup_web_ai_price as _look
    _found = _look({
        "description": _brief.get("description"),
        "part_code": _brief.get("code"),
        "quantity": _brief.get("order_quantity"),
        # WHAT THE LINE IS BOUGHT BY. Edging is sold by the metre and board by the sheet
        # or the square metre; asked for "one ABS edging" a model prices a REEL, and the
        # reel price then gets multiplied by the metres. The producer refuses a figure in
        # the wrong unit, and this is how the researcher is told which unit to answer in
        # so it does not have to be refused in the first place.
        "wanted_unit": _brief.get("wanted_unit"),
        "ask": _brief.get("ask"),
        "supply": ("bought_in" if _brief.get("kind") == "bought_in_component" else ""),
    }) or {}
    if not _found.get("found"):
        return {}
    return {
        "price_gbp": _found.get("price_gbp"),
        "unit": _found.get("unit"),
        # THE DATE, WHICH NEVER ARRIVED AND WITHOUT WHICH NOTHING COULD EVER BE PRICED.
        #
        # The producer requires four things before a researched figure may be used — a
        # source, the date it was true, what it is per, and the quantity it was found at —
        # and refuses the price outright if any is missing. That refusal is right and is
        # the reason rung 4 is allowed to contribute to a total at all.
        #
        # The lookup stamps the date on every result it returns, under `price_date`. This
        # adapter read `as_of`. So the date was present, recorded, correct, and dropped in
        # the six lines between the two modules — and EVERY researched price this engine
        # has ever found was refused for want of a date it already had. A fact written
        # under one name and read under another, again, and this time it made a whole rung
        # of the ladder inert without a single error anywhere.
        "as_of": (_found.get("as_of") or _found.get("price_date") or ""),
        "source": (_found.get("source_url") or _found.get("source")
                   or _found.get("search_provider")
                   or _found.get("llm_provider") or ""),
        "quantity_basis": (_found.get("price_basis")
                           or _found.get("quantity_basis") or ""),
        "origin": _found.get("source_type"),
        # ── AND WHETHER IT WILL SAY THE SAME THING TOMORROW ──────────────────────
        #
        # James Gray, 22 Sep 2026, on the second concept book: "The hinge and four castors
        # are still £0. That is against your standing rule: visible bought-ins must enter
        # the pricing pipeline."
        #
        # THE FIGURE WAS FOUND AND THEN THROWN AWAY BY A MISSING KEY — the same shape as
        # the date three lines above, one layer down. `lookup_web_ai_price` asks once per
        # specification and stores the answer, and returns `price_is_reproducible` to say
        # so. This adapter did not carry it. `indicative_price_to_withhold` then found an
        # AI figure with nothing saying it holds still, and did the one thing it is for:
        # kept it off the price column. So the castors showed £48.16 in one table and
        # "no price" in another, and the money column read £0.
        #
        # Reproducibility is the WHOLE test that rule turns on — "a guess that changes
        # every run is not a price" — and this figure passes it. Carrying the flag is not
        # a relaxation of the policy; it is the policy finally being asked about the right
        # thing.
        "price_is_reproducible": bool(_found.get("price_is_reproducible")),
        "price_first_taken": _found.get("price_first_taken") or "",
        # What the model says it priced, in its own words, and per what.
        "item_priced": _found.get("item_priced") or "",
    }


def _researched_board_rate_m2(material: Optional[str], thickness: Optional[float],
                              part: Dict[str, Any], noun: str = "board"):
    """An evidenced researched £/m² for a board nothing else can price, or None.

    James Gray, 17 September 2026: "it's lame not to price the MDF and Tony is sarcastic
    and will laugh about it."

    He is right, and the reason it read as unpriced was a gap in the ladder rather than a
    rule. Rung 4 — a researched figure that names its source, its date, what it is per and
    the arithmetic — was built for BOUGHT-IN lines and wired only into that chain. A board
    is a material, so it fell off the bottom of the ladder after rung 1 (SDI Live / the
    UDEF catalogue) missed, and there was nothing below it. Rung 4 is not a property of
    being a bought-in; it is the last rung, and every line is entitled to it.

    Priced PER SQUARE METRE, because that is the only basis that survives a change of stock
    size: a £/sheet figure is worthless without the sheet it was for, and the two travel
    apart. The area is the part's own blank, so the arithmetic is the same one the live
    catalogue branch does and an estimator compares like with like.

    Returns the producer's own dict (price, evidence, calculation, status) or None. It
    cannot return a figure without evidence — that refusal is the producer's, and is the
    whole reason this is allowed to contribute to a total at all.
    """
    _l = _safe_float(part.get("blank_length_mm"))
    _w = _safe_float(part.get("blank_width_mm"))
    if not _l or not _w or not material:
        return None
    _area_m2 = round((_l * _w) / 1_000_000.0, 6)
    if _area_m2 <= 0:
        return None
    _thk = _safe_float(thickness)
    # THE NOUN IS THE CALLER'S. Asking the market for "2mm PETG board" gets an answer
    # about the wrong product; a plastic is bought as sheet. The rung is the same rung —
    # only the word for what is being bought changes.
    _desc = (f"{_thk:g}mm {str(material).replace('_', ' ')} {noun}"
             if _thk else f"{str(material).replace('_', ' ')} {noun}")
    # ONE BOARD, ONE RATE, ONE LOOKUP.
    #
    # 11908-21 has three parts cut from the same 9mm sheet. Researched per part, that is
    # three calls to a language model about one board — and, worse than the waste, three
    # ANSWERS. A sheet showing the same material at three different £/m² is not a rounding
    # difference an estimator can wave through; it is visibly incoherent, and it would be
    # this engine's own doing. Cached on the FAMILY AND THE GAUGE, which is what the rate
    # is a property of, for the life of the run.
    _rate_key = (str(material).upper(), round(float(_thk), 1) if _thk else None)
    if _rate_key in _RESEARCHED_BOARD_RATE_CACHE:
        _hit = _RESEARCHED_BOARD_RATE_CACHE[_rate_key]
        if not _hit:
            return None
        # The rate is per square metre and this part has its own area, so the MONEY is
        # recomputed for this blank — only the researched RATE is shared.
        _unit = _safe_float(_hit.get("unit_price_gbp"))
        if _unit is None:
            return None
        _out = dict(_hit)
        _out["price_gbp"] = round(_unit * _area_m2, 4)
        _out["calculation"] = {
            "per_unit_gbp": round(_unit * _area_m2, 4),
            "working": (f"{_area_m2:g} square metre x GBP {_unit:,.4f} a square metre "
                        f"= GBP {_unit * _area_m2:,.4f} a unit (rate already researched "
                        f"for this board on this run)")}
        return _out
    try:
        from indicative_price import resolve_indicative as _rung4
        _out = _rung4(
            {"code": "", "description": _desc, "quantity": _area_m2,
             "unit_of_measure": "m2",
             # THE PROVENANCE OF EVERY INPUT, so the producer's contamination guard can do
             # its job. The area is measured off the drawing; nothing here came off an
             # estimator's sheet, and if it ever does the brief is refused rather than
             # laundered into a researched answer.
             "input_origins": {"description": "drawing_or_measurement",
                               "quantity": "drawing_or_measurement"}},
            order_qty=int(_safe_float(part.get("job_quantity")) or 1),
            as_of=str(part.get("run_date") or ""),
            ask=_rung4_researcher,
        )
    except Exception:                                            # noqa: BLE001
        _RESEARCHED_BOARD_RATE_CACHE[_rate_key] = None
        return None
    if not _safe_float((_out or {}).get("price_gbp")):
        # A MISS IS CACHED TOO. Without it, a board nothing can price is researched again
        # for every part cut from it — the slowest possible way to learn the same thing.
        _RESEARCHED_BOARD_RATE_CACHE[_rate_key] = None
        return None
    _RESEARCHED_BOARD_RATE_CACHE[_rate_key] = _out
    return _out


def _faced_board_promotion(part: Dict[str, Any], material: Optional[str]):
    """(faced family, the evidence sentence) when a plain board core is LAMINATED — or
    (None, "").

    THE SHOP DOES NOT LAMINATE; THE MERCHANT DOES. 11908-21's trays are drawn as 9mm MDF
    with a LAMINATED finish — the DXFs are named "9mm MDF+ LAM" and the route demanded a
    `laminating` operation nothing could price, so the job costed plain MDF at £1.35/kg
    (£43 a sheet) and flagged the laminate as supplied free. Tony's estimate shows the
    actual transaction: a pre-laminated board bought by the sheet from Lawcris at four
    times the raw-MDF money. The material IS the finish, so the promotion is to the faced
    family — its stock sizes, its purchased sheet prices — and the laminating on the
    route is satisfied by the purchase, not charged as shop labour.

    Evidence is required, never inferred from the material name alone: the route's own
    `laminating` op, a LAMINATE/MELAMINE finish field, a "LAM" token in the cut file's
    name, or the word in the part's description. Plain MDF stays plain MDF.
    """
    mat = str(material or "").upper().replace("_", " ")
    if any(t in mat for t in ("MFMDF", "MFC", "MELAMINE", "VENEER", "PRE LAM", "PRE-LAM")):
        return None, ""            # already a faced family — nothing to promote
    if "MDF" in mat:
        family = "MFMDF"
    elif "CHIPBOARD" in mat or mat == "OSB":
        family = "MFC"
    else:
        return None, ""
    evidence: List[str] = []
    # THE STRONGEST RUNG FIRST: the drawing's own material field NAMED the faced family
    # (MFMDF, melamine-faced), and the canonical collapse to plain MDF kept that word
    # beside the part rather than discarding it. A title block that says MFMDF should not
    # need the laminate found again in a finish note or a file name.
    if str(part.get("_stated_faced_family") or "").upper() == family:
        evidence.append(f"the drawing's own material field ({family} stated outright)")
    _ops = {str(o).lower() for o in ((part.get("operations") or [])
                                     + (part.get("textual_operations") or []))}
    if "laminating" in _ops or "laminate" in _ops:
        evidence.append("the route's own `laminating` operation (a drawing note)")
    _finish = " ".join(str(x) for x in (
        part.get("normalized_finish"), part.get("surface_finish"),
        " ".join(str(v) for v in (part.get("surface_finishes") or []))) if x).upper()
    if any(w in _finish for w in ("LAMINAT", "MELAMINE")):
        evidence.append(f"the stated finish ('{_finish[:40].strip()}')")
    _dxf = str(part.get("dxf_source_file") or "").upper()
    if re.search(r"(?:^|[\s_+-])LAM(?:INAT\w*)?(?:[\s_.+-]|$)", _dxf):
        evidence.append(f"the cut file's own name ({part.get('dxf_source_file')})")
    if "LAMINAT" in str(part.get("description") or "").upper():
        evidence.append("the part's description")
    if not evidence:
        return None, ""
    return family, " and ".join(evidence[:2])


def _board_sheet_rate(material: Optional[str], thickness: Optional[float]):
    """(GBP per full sheet, how it was arrived at) for a faced board, or (None, "").

    INTERPOLATED BETWEEN PURCHASES, NEVER EXTRAPOLATED BEYOND THEM. config records the
    thicknesses SDI has actually bought — 18mm and 36mm of the same Egger board, from priced
    jobs eighteen months apart. A thickness between them is the estimator's own arithmetic on
    the shop's own numbers. A thickness OUTSIDE them is not: nothing in the history says what
    a 50mm board costs, and a straight-line guess past the last real point is the kind of
    number that looks derived and is invented. Those stay unpriced and visible.
    """
    table = (getattr(config, "BOARD_SHEET_PRICE_GBP", {}) or {}).get(
        str(material or "").upper().replace(" ", "_"))
    if not isinstance(table, dict) or not table:
        table = (getattr(config, "BOARD_SHEET_PRICE_GBP", {}) or {}).get(
            str(material or "").upper())
    thk = _safe_float(thickness)
    if not isinstance(table, dict) or not table or not thk or thk <= 0:
        return None, ""
    # A point may be a plain price, or {"gbp": …, "sheet_mm": (L, W)} when the size the
    # price was PAID FOR matters — _board_priced_sheet_mm reads the size; this reads money.
    # A WITHDRAWN POINT IS NOT A POINT. Every price in this table was withdrawn on
    # 18 Sep 2026 (D-103): the 9mm figure was off Tony's own estimate and the Dibond ones
    # were a mid-trade guess. What remains is the material families and the SHEET SIZES,
    # which are specification rather than money and which his other complaint depended on.
    # A point with no money is skipped here so the line falls to the rungs that can answer
    # — and with no points at all this returns None, which is the honest answer.
    points = []
    for t, p in table.items():
        _gbp = p.get("gbp") if isinstance(p, dict) else p
        if _gbp is None:
            continue
        try:
            points.append((float(t), float(_gbp)))
        except (TypeError, ValueError):
            continue
    points.sort()
    for _t, _p in points:
        if abs(_t - thk) < 0.51:
            return _p, f"observed at {_t:g}mm"
    lo = [pt for pt in points if pt[0] < thk]
    hi = [pt for pt in points if pt[0] > thk]
    if not lo or not hi:
        return None, ""
    (t0, p0), (t1, p1) = lo[-1], hi[0]
    rate = p0 + (p1 - p0) * (thk - t0) / (t1 - t0)
    return round(rate, 2), (f"interpolated for {thk:g}mm between SDI's own {t0:g}mm "
                            f"(£{p0:.2f}) and {t1:g}mm (£{p1:.2f})")


def _board_priced_sheet_mm(material: Optional[str], thickness: Optional[float]):
    """(sheet_length, sheet_width) the recorded board price was PAID FOR, or None.

    £172 buys a 3080x1220 of the 9mm laminated board; the stocked-size list also offers a
    2800x2070, which yields more parts — and dividing the 3080x1220's money by the
    2800x2070's yield understates every part on the job. Where a price point states its
    sheet, the yield must be computed on that sheet and no other."""
    table = (getattr(config, "BOARD_SHEET_PRICE_GBP", {}) or {}).get(
        str(material or "").upper().replace(" ", "_")) or \
        (getattr(config, "BOARD_SHEET_PRICE_GBP", {}) or {}).get(
            str(material or "").upper())
    thk = _safe_float(thickness)
    if not isinstance(table, dict) or not thk:
        return None
    for _t, _p in table.items():
        if abs(float(_t) - thk) < 0.51 and isinstance(_p, dict) and _p.get("sheet_mm"):
            _s = _p["sheet_mm"]
            try:
                return (float(_s[0]), float(_s[1]))
            except (TypeError, ValueError, IndexError):
                return None
    return None


def _powder_consumable_estimate(
    part: Dict[str, Any],
    blank_length: Optional[float],
    blank_width: Optional[float],
    quantity: int,
) -> Dict[str, Any]:
    """
    Powder material cost — matches workbook AB:AC:AD formula (cols AB-AD, rows 38-48):

        AB = (part_length_m × part_width_m) × 2        [both faces, m²]
        AC = 6 / AB                                     [parts per kg — coverage = 6 m²/kg]
        AD = (1 / AC) × qty_per_unit                    [kg per unit = area_m2 × 2 / 6]

    Simplified:  powder_kg_per_unit = blank_area_m2 × coated_faces_multiplier / coverage_m2_per_kg
    Workbook coverage constant = 6 m²/kg (hard-coded). Platform reads from POWDER_COSTING_POLICY.
    """
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    if not policy.get("enabled", True):
        return {}
    if "powder_coating" not in _part_ops(part):
        return {}
    if blank_length is None or blank_width is None or blank_length <= 0 or blank_width <= 0:
        return {}

    L_m = float(blank_length) / 1000.0
    W_m = float(blank_width) / 1000.0

    # Workbook AB: area = (L_m × W_m) × 2  (both faces, no bend strips in workbook formula)
    # Platform extends this with optional bend-edge strips for higher accuracy.
    faces_m, faces_reason = _effective_coated_faces_multiplier(part)
    flat_area_m2 = L_m * W_m * faces_m          # workbook: faces_m = 2.0 always
    bend_extra_m2 = 0.0
    strip_mm = float(policy.get("bend_coating_strip_mm", 40.0))
    bends, _ = _bends_for_coating(part)
    fold_vals = part.get("fold_values_mm") or []
    perimeter_fold_mm = sum(_safe_float(x) or 0.0 for x in fold_vals)
    if perimeter_fold_mm > 0:
        bend_extra_m2 = (perimeter_fold_mm / 1000.0) * (strip_mm / 1000.0) * 2.0
    elif bends > 0:
        bend_extra_m2 = bends * (strip_mm / 1000.0) * min(L_m, W_m) * 2.0
    total_area_m2 = flat_area_m2 + bend_extra_m2

    # Workbook AC/AD: kg_per_unit = total_area_m2 / coverage_m2_per_kg
    coverage = float(policy.get("coverage_m2_per_kg", 6.0))   # workbook = 6.0
    kg_raw = total_area_m2 / coverage if coverage > 0 else 0.0

    scrap_mult = 1.0
    if policy.get("apply_global_scrap_to_powder_kg", True):
        scrap_mult = 1.0 + float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
    kg_per_unit = kg_raw * scrap_mult

    price_per_kg, price_tier = _resolve_powder_material_price_per_kg(part)
    unit_cost = kg_per_unit * price_per_kg if price_per_kg > 0 else 0.0
    extended = unit_cost * quantity

    return {
        "workbook_formula": "AD = (1/AC) × qty = area_m2×2/6 per unit",
        "coverage_m2_per_kg": coverage,
        "flat_area_m2": round(flat_area_m2, 6),
        "bend_extra_coated_m2": round(bend_extra_m2, 6),
        "coated_area_m2": round(total_area_m2, 6),
        "coated_faces_multiplier": faces_m,
        "coated_faces_reason": faces_reason,
        "bend_lines_used": bends,
        "kg_powder_per_unit": round(kg_per_unit, 6),
        "powder_material_gbp_per_kg": price_per_kg,
        "powder_price_tier": price_tier,
        "scrap_multiplier_on_kg": scrap_mult,
        "unit_powder_material_cost_gbp": round(unit_cost, 4) if price_per_kg > 0 else None,
        "extended_powder_material_cost_gbp": round(extended, 2) if price_per_kg > 0 else 0.0,
        "priced": price_per_kg > 0,
    }


def estimate_blank_size(dimensions: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    length = dimensions.get("overall_length_mm")
    width = dimensions.get("overall_width_mm")
    if length is None or width is None:
        return None, None

    # Keep part blank equal to extracted flat pattern dimensions.
    # Sheet-level edge margin is applied in select_sheet_size().
    return round(length, 2), round(width, 2)


def _blank_has_a_direction(part: Optional[Dict[str, Any]]) -> bool:
    """Does anything about this part run one way across the sheet?

    A brushed panel nested sideways is a panel the customer rejects, and no yield pays for
    that. Judged on tokens from the material, finish and description — never a part number —
    so a job nobody has seen yet is judged by the same rule.
    """
    if not isinstance(part, dict):
        return False
    _blob = " ".join(str(part.get(k) or "") for k in
                     ("normalized_material", "material", "finish", "normalized_finish",
                      "description", "part_number")).upper()
    return any(t in _blob for t in getattr(config, "DIRECTIONAL_FINISH_TOKENS", ()))


def select_sheet_size(material: Optional[str], blank_length: Optional[float], blank_width: Optional[float],
                      part: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    EXACT template nesting formula — Estimate sheet, Sheet Steel section, cell K38:
        nx (length axis) = INT(  sheet_length        / (part_length + 20) )   <- no edge margin, +20 gap
        ny (width  axis) = INT( (sheet_width  - 80)  / (part_width  + 10) )   <- 80mm margin, +10 gap
        parts_per_sheet  = nx × ny
    Mapping to template columns: F=Part Length -> I=Sheet Length axis; G=Part Width -> J=Sheet Width axis.
    FIXED ORIENTATION — the template does not rotate parts (no best-of-two-orientations). Part length
    always nests along sheet length, part width along sheet width, exactly as K38 does.
    Template guards: a part dimension of 0, or larger than the sheet in that axis, yields "doesn't fit".

    NOTE: K38 is the STEEL rule. The 'Other Sheet Material' section (plastic/board, cell J51) uses
    a different one (−5 margin, +20 on the width axis). This function used to run K38 over every
    material and this note used to say the other case was "handled separately for non-steel
    materials" — it was handled in the plastic COST path only, so every plastic part still carried
    the steel nest in its stock_estimate while being charged by J51. The rule now follows the
    MATERIAL, through the same classifier that decides which workbook block the part lands in.
    """
    if blank_length is None or blank_width is None:
        return {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}

    sizes = STANDARD_SHEET_SIZES_MM.get(material or "", STANDARD_SHEET_SIZES_MM["DEFAULT"])

    best: Optional[Dict[str, Any]] = None
    # THE TEMPLATE NEVER ROTATES, SO THE ENGINE TURNS THE BLANK BEFORE THE TEMPLATE SEES IT.
    #
    #   "Line 84 – AI Yield 24 Per Sheet – if Component, Exchange Length for Width and Vice
    #    Versa   Yield is 26 Per Sheet"      — Howard Thurley, 0355255, 9 Sep 2026
    #
    # He is right, and the fix cannot live in the nest formula: the workbook recomputes the
    # yield itself from the dims we write, by the same fixed-orientation rule. So both
    # orientations are tried HERE, and when the turned one nests better the caller writes
    # the blank turned — the sheet then reaches 26 by its own arithmetic, and the JSON and
    # the workbook still agree, which is the invariant this function exists to keep.
    #
    # Never for a blank with a direction: a brushed or grained panel nested sideways is a
    # reject, and no yield pays for that.
    # ONLY WHEN THE CALLER HANDS THE PART OVER. Turning the blank is only honest when the
    # caller also WRITES it turned — a call site that takes parts_per_sheet without owning
    # the written dims would put a rotated yield beside unrotated dimensions, and the
    # workbook would recompute the old 24 against a JSON saying 26: the exact disagreement
    # this function exists to prevent. No part, no rotation.
    # AND ONLY FOR THE SHEET PLASTICS, for now. A steel blank turned changes which way the
    # bends run against the rolling direction, and a faced board turned runs its oak the
    # wrong way across the panel — both are questions for the shop, not yields to bank.
    # Acrylic and its siblings have no grain, which is Howard's case and the one banked.
    _orientations = [(blank_length, blank_width, False)]
    _sheet_plastic = str(material or "").upper() in getattr(
        config, "PLASTIC_SHEET_PRICED_MATERIALS", frozenset())
    if (part is not None and _sheet_plastic and blank_length != blank_width
            and not _blank_has_a_direction(part)):
        _orientations.append((blank_width, blank_length, True))
    for sheet_length, sheet_width in sizes:
        for _bl, _bw, _turned in _orientations:
            # No separate "bigger than the sheet" guard: a part that does not fit comes back
            # as no nest at all, because the gap and the margin are subtracted before the
            # division.
            nest = _costed_facts.nest_on_sheet(material, _bl, _bw,
                                               sheet_length, sheet_width)
            if not nest:
                continue
            qty = nest["parts_per_sheet"]
            utilisation = (qty * _bl * _bw) / (sheet_length * sheet_width) * 100.0
            candidate = {
                "candidate_sheet_size_mm": [sheet_length, sheet_width],
                "utilisation_pct": round(utilisation, 2),
                "rotated": _turned,
                **nest,
            }
            # The better yield wins; on a tie the unturned blank stands, because turning is
            # a change somebody may have to explain and a tie buys nothing for it.
            if best is None or qty > best["parts_per_sheet"]:
                best = candidate

    return best or {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}


def _canonical_material_family(raw: Any) -> Any:
    """Map a raw title-block material string to the canonical family the cost/density/routing
    tables key on. Timber drawings print species/grades (FSC PINE, MRMDF, SPRUCE, OAK VENEER)
    that never matched TIMBER/MDF, so those parts had no price and fell through to the sheet
    path as phantom mild steel. This normalises them. Metals/plastics pass through unchanged
    (only maps when a timber/board token is present)."""
    u = str(raw or "").upper()
    if not u:
        return raw
    if "MDF" in u:                                   # MRMDF, MR MDF, VENEERED MDF, OAK VENEER MDF
        return "MDF"
    if "PLYWOOD" in u or "PLYWD" in u or " PLY" in u or u.endswith("PLY"):
        return "PLYWOOD"
    if any(t in u for t in ("PINE", "SPRUCE", "SOFTWOOD", "HARDWOOD", "TIMBER", "WOOD",
                            "OAK", "BEECH", "BIRCH", "FSC")):
        return "TIMBER"
    if "BOARD" in u:                                 # generic board / soft-touch laminate board
        return "MDF"
    return raw


def _blank_that_could_have_been_cut(
    part: Dict[str, Any],
    blank_length: Optional[float],
    blank_width: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    """Refuse a blank the part's own cut path proves impossible, before it prices anything.

    Job 12392's back panel reached this function as 16 x 3.7 mm carrying a 6,679 mm cut
    path — six and a half metres of cutting inside a rectangle the size of a staple. It
    priced at GBP 0.01 and the sheet claimed 5,865 of them out of one 2500 x 1250, on what
    is almost certainly the largest part in the job.

    The invariant caught it and blocked the quote. This function is why that was not
    enough: the check ran after the workbook had already been written, so the number was
    named as wrong and used anyway. A rule that only reports arrives too late to matter.

    WHAT REPLACES IT. The modelled bounding box, when there is one that could have held
    the cut. A bounding box UNDER-states a developed length — a folded part unfolds longer
    than the box it folds into — so this is a floor and is stamped as one. A floor is worth
    having only because the alternative here is wrong by a hundredfold, and an estimator
    correcting a low number is in a better position than one who never saw the part.

    WHEN NOTHING SURVIVES, NOTHING IS RETURNED. The part then carries no blank, prices no
    material, and says so. Inventing a plausible-looking size is precisely the failure this
    exists to end.
    """
    if not blank_length or not blank_width:
        # No blank to judge. Absence is another check's business, and reasoning about a
        # value that is not there is how this function came to format None as a number.
        return blank_length, blank_width
    try:
        import blank_credibility as _bc
    except ImportError:                                            # pragma: no cover
        return blank_length, blank_width

    _pn = str(part.get("part_number") or "?")
    _flags = part.setdefault("review_flags", [])
    # Kept before the clearing below, because the inference needs the overalls the
    # drawing printed and the clearing removes them — the first version read them AFTER
    # they had been nulled and silently inferred nothing.
    _orig_l, _orig_w = blank_length, blank_width
    _orig_overall_l = _safe_float(part.get("overall_length_mm"))
    _orig_overall_w = _safe_float(part.get("overall_width_mm"))
    _folded = bool(part.get("bend_count") or part.get("fold_count")) or any(
        _op in (part.get("textual_operations") or []) for _op in ("folding", "bending"))
    _bbox_raw = []
    for _h in (part, part.get("normalized_geometry") or {}, part.get("native_geometry") or {}):
        if isinstance(_h, dict) and isinstance(_h.get("bbox_mm"), (list, tuple)):
            _bbox_raw = list(_h["bbox_mm"])
            break

    # ONLY A MEASURED CUT PATH IS EVIDENCE. estimated_cut_length_mm is the PDF page
    # reader's sum of every vector on the sheet — borders, views, dimension lines, title
    # block — at 72 points to the inch with no drawing scale. On 12392 that produced a
    # "6,679 mm cut path" for a part with no flat at all, and comparing it to a blank
    # scraped off the same sheet was two pieces of nonsense agreeing about nothing.
    cut = None
    for holder in (part, part.get("normalized_geometry") or {},
                   part.get("geometry_rollup") or {}):
        if not isinstance(holder, dict):
            continue
        for key in ("cut_length_mm", "dxf_measured_cut_length", "total_cut_length_mm"):
            value = _safe_float(holder.get(key))
            if not value:
                continue
            _src = (holder.get(f"{key}_source") or holder.get("geometry_source")
                    or part.get("geometry_source"))
            if _bc.cut_path_is_measured(_src):
                cut = value
                break
        if cut:
            break

    # A BLANK IS EVIDENCE ONLY IF SOMETHING MEASURED IT. Refusing the page-summed cut
    # path above removed the only thing that had been catching a bad blank — the pair
    # test needs both numbers, and one of them has just been correctly disqualified. So
    # the blank is now judged on its own provenance, which is the policy's rule 3: a page
    # vector sum or a dimension scraped off the sheet is never blank evidence.
    #
    # An UNSTAMPED blank is not assumed measured. 12392's 16 x 3.7 carried no source at
    # all, which is precisely what made it impossible to argue with.
    _blank_src = (part.get("blank_length_mm_source")
                  or (part.get("normalized_geometry") or {}).get("blank_length_mm_source")
                  or part.get("geometry_source"))
    _blank_measured = _bc.cut_path_is_measured(_blank_src)

    verdict = _bc.assess(blank_length, blank_width, cut)
    if verdict["evaluated"] and not verdict["credible"]:
        pass                       # measured or not, the pair is impossible
    elif _blank_measured:
        return blank_length, blank_width
    elif _bc.fits_a_stock_sheet(blank_length, blank_width,
                                part.get("normalized_material")) is False:
        # IT DOES NOT FIT ANY SHEET THIS MATERIAL COMES IN, so it is not this part's blank.
        #
        # The bound above asks only whether a number is between 10 mm and 4 m, and 12349-02's
        # 2120 x 2120 passed it comfortably — while being the drawing sheet's own bounding
        # box, read as "the largest numbers in the document text". Excel had already worked
        # out that it was wrong: nothing 2120 square nests on a 2050 x 1520 acrylic sheet, so
        # Qty Per Sheet came back empty, Cost Per Part came back empty, and the two LARGEST
        # parts on the job contributed nothing to the material total while sitting on the
        # sheet as ordinary rows. A part that silently costs nothing is worse than one that is
        # refused, because a refusal is at least visible — and the same bounding box went on
        # to size the packaging and the haulage.
        _sheet = _bc.largest_stock_sheet(part.get("normalized_material"))
        verdict = {"evaluated": True, "credible": False,
                   "reason": (f"a {blank_length:g} x {blank_width:g} mm blank does not fit "
                              f"any sheet "
                              + (f"{part.get('normalized_material')} " if part.get(
                                  "normalized_material") else "")
                              + f"is stocked in"
                              + (f" (largest is {_sheet[0]:g} x {_sheet[1]:g})"
                                 if _sheet else "")
                              + " — this is a bounding box or a drawing sheet size, not the "
                                "part"
                              + (f" (source: {_blank_src})" if _blank_src else ""))}
    elif _bc.plausible_as_a_sheet_part(blank_length, blank_width):
        # Unstamped, but it could be the size of something we cut and nothing contradicts
        # it. Keep it — refusing every unstamped blank stopped a 120 x 80 bracket costing
        # at all, on a part whose cut path fits it perfectly. Flagged, not trusted.
        if "blank_source_not_recorded" not in _flags:
            _flags.append("blank_source_not_recorded")
        return blank_length, blank_width
    else:
        verdict = {"evaluated": True, "credible": False,
                   "reason": (f"a {blank_length:g} x {blank_width:g} mm blank is not the "
                              f"size of a sheet fabrication and nothing measured it"
                              + (f" (source: {_blank_src})" if _blank_src else ""))}


    # The bounding box, from wherever the native read put it. Offered as a floor only.
    _bbox = sorted([v for v in (_safe_float(b) for b in _bbox_raw) if v], reverse=True)
    candidates = ()
    if len(_bbox) >= 2:
        candidates = (("solidworks bounding box (a floor — a folded part unfolds longer)",
                       _bbox[0], _bbox[1]),)

    better = _bc.better_blank_from(candidates, cut)
    if better:
        part["blank_length_mm"] = better["blank_length_mm"]
        part["blank_width_mm"] = better["blank_width_mm"]

        # A FLOOR ONLY WHERE IT IS ONE. "bounding_box_floor" ranks ZERO — fills gaps,
        # never displaces anything — which is right for a folded part, whose box under-
        # reads the blank it unfolds from. It is wrong for a part the model proves never
        # leaves the plane: there the envelope IS the blank, measured, and stamping it at
        # rank 0 left a 1435 x 130 figure off the model open to replacement by a rank-20
        # inference, silently, on the two numbers that drive both the laser and the
        # material cost.
        #
        # The derived datum inherits the source of the measurement it rests on, and no
        # more: strip the source off the bbox and this falls straight back to a floor.
        _bbox_src = str(part.get("bbox_mm_source")
                        or (part.get("normalized_geometry") or {}).get("bbox_mm_source")
                        or "").strip()
        _flat = _bc.envelope_proves_it_never_leaves_the_plane(
            _bbox_raw, part.get("normalized_thickness_mm"))
        if _flat and _bc.cut_path_is_measured(_bbox_src):
            part["blank_length_mm_source"] = _bbox_src
            part["blank_width_mm_source"] = _bbox_src
            part["blank_replaced_reason"] = verdict["reason"]
            if "blank_replaced_by_measured_envelope" not in _flags:
                _flags.append("blank_replaced_by_measured_envelope")
            print(f"   [blank] {_pn}: recorded blank rejected — {verdict['reason']}. "
                  f"Priced from the {_bbox_src} envelope instead: "
                  f"{better['blank_length_mm']:g} x {better['blank_width_mm']:g} mm. "
                  f"The envelope is {min(_bbox):g} mm deep — the material thickness — so "
                  f"nothing leaves the plane and this IS the blank, not a floor under it.",
                  flush=True)
            return better["blank_length_mm"], better["blank_width_mm"]

        part["blank_length_mm_source"] = "bounding_box_floor"
        part["blank_width_mm_source"] = "bounding_box_floor"
        part["blank_replaced_reason"] = verdict["reason"]
        if "blank_replaced_by_bounding_box_floor" not in _flags:
            _flags.append("blank_replaced_by_bounding_box_floor")
        print(f"   [blank] {_pn}: recorded blank rejected — {verdict['reason']}. "
              f"Priced from the {better['source']} instead: "
              f"{better['blank_length_mm']:g} x {better['blank_width_mm']:g} mm. "
              f"UNDER-STATES a folded part — estimator to confirm.", flush=True)
        return better["blank_length_mm"], better["blank_width_mm"]

    # CLEAR IT EVERYWHERE IT IS WRITTEN, not just where it is read first. The rejected
    # 16 x 3.7 went on blocking the job after this gate refused it, because the invariant
    # falls back to overall_length_mm and normalized_geometry when blank_length_mm is
    # absent — so removing one copy simply moved which copy got believed.
    for _holder in (part, part.get("normalized_geometry"), part.get("geometry_rollup")):
        if isinstance(_holder, dict):
            for _key in ("blank_length_mm", "blank_width_mm", "blank_area_mm2",
                         "overall_length_mm", "overall_width_mm"):
                if _holder.get(_key) is not None:
                    _holder[_key] = None
    # PRIORITY 2: the overall size the DETAIL prints. Nothing measured a flat, so the
    # drawing's own number is the best there is — and pricing from it beats leaving a
    # material gap on a part we cut ourselves. Marked inferred, ranked below measured,
    # and put on the estimator's list to confirm.
    _inf = _bc.blank_from_drawing_overalls(
        _orig_overall_l or _orig_l,
        _orig_overall_w or _orig_w,
        _safe_thickness_mm(part),
        is_folded=bool(_folded),
        developed_length_mm=part.get("developed_length_mm"),
        bbox_mm=_bbox_raw,
    )
    if _inf.get("usable"):
        part["blank_length_mm"] = _inf["blank_length_mm"]
        part["blank_width_mm"] = _inf["blank_width_mm"]
        part["blank_length_mm_source"] = _inf["source"]
        part["blank_width_mm_source"] = _inf["source"]
        part["geometry_source"] = _inf["source"]
        part["blank_is_inferred"] = True
        part["blank_inferred_reason"] = _inf["reason"]
        if "blank_inferred_from_drawing_overalls" not in _flags:
            _flags.append("blank_inferred_from_drawing_overalls")
        print(f"   [blank] {_pn}: {_inf['reason']} "
              f"({_inf['blank_length_mm']:g} x {_inf['blank_width_mm']:g} mm).", flush=True)
        return _inf["blank_length_mm"], _inf["blank_width_mm"]

    part["blank_rejected_reason"] = verdict["reason"]
    if "blank_impossible_no_replacement" not in _flags:
        _flags.append("blank_impossible_no_replacement")
    # Say why NOTHING could replace it, not merely that nothing did. "Estimator to size"
    # is a task; "folded, and no flat pattern or developed length is stated" is the same
    # task with the answer attached.
    part["blank_needs_sizing_reason"] = _inf.get("reason") or verdict["reason"]
    print(f"   [blank] {_pn}: recorded blank rejected — {verdict['reason']}. "
          f"No usable replacement: {part['blank_needs_sizing_reason']}. "
          f"NO blank and NO material cost — ESTIMATOR TO SIZE.", flush=True)
    return None, None


def _material_we_can_actually_price(part: Dict[str, Any], material: Any) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """The material to PRICE from, and the conflict record if it is not the arbitrated one.

    THE RANK-WINNING VALUE IS NOT ALWAYS THE COSTABLE ONE. Arbitration ranks sources by how
    well they know what a part IS. It says nothing about whether this engine holds a rate for
    the answer, and on 11650-01-05A DOOR those came apart: SolidWorks (rank 90) said ABS,
    which has no entry in the plastic sheet gate and none in MATERIAL_PRICE_GBP_PER_KG; the
    drawing text (rank 70) said POLYCARBONATE, which has both. A 1202 x 689 x 6mm door
    costed GBP 0.00 of material, and the estimate was silently short by about GBP 18.69.

    THREE THINGS THIS MUST NOT DO.

    It must not change normalized_material. What the part IS remains the arbitration's
    answer -- a lower-ranked source does not win a datum by being convenient, and the
    reports must keep showing what the model said.

    It must not improve a total quietly. The substitution is recorded on the part and
    reported as a conflict an estimator has to rule on; a number that appears with no
    explanation is the failure this whole layer exists to stop.

    It must not fire when the winner is priceable. A rate that exists is used, whatever else
    was read. This is a rescue for an unpriceable winner, not a preference for cheap answers.
    """
    if config.material_has_a_rate(material):
        return material, None
    # AND THE LIVE SHEET CATALOGUE IS A RATE. THIS ASKED ONE SOURCE AND SPOKE FOR ALL OF THEM.
    #
    # config.material_has_a_rate reads MATERIAL_PRICE_GBP_PER_KG and nothing else. It has
    # never heard of the customer's own parts catalogue, which is where PETG, ABS and HIPS
    # sheet prices actually live — so a material with 37 rows of live stock behind it was
    # judged unpriceable and rescued to ACRYLIC.
    #
    # 11650-04 IS WHAT THAT COSTS, AND IT IS THE SPLIT NOBODY COULD EXPLAIN. The two detail
    # panels were rescued to ACRYLIC and charged GBP 48.89 a sheet from a config figure; their
    # own handed twins reached the catalogue and were charged GBP 60.21 for the identical
    # PETG 2.0. One stock key, one purchase, two prices — and the rescue was the writer of the
    # cheaper one, on a job where PETG was the right answer all along.
    #
    # "Can we price this material" is ONE question and must have one answer. Asking a single
    # table and treating silence as no-rate-anywhere is the dual-path defect in the money.
    try:
        if _resolve_board_sheet_rate_gbp_per_m2(material, part.get("normalized_thickness_mm")):
            return material, None
    except Exception:                                        # noqa: BLE001
        pass
    # Everything else this part was read as, best-evidenced first: what arbitration displaced,
    # then the raw tokens off the drawing.
    seen, candidates = set(), []
    for entry in (part.get("_displaced") or {}).get("normalized_material") or []:
        if isinstance(entry, dict) and entry.get("value"):
            candidates.append((entry["value"], entry.get("source") or "an earlier pass"))
    for token in (part.get("materials") or []):
        candidates.append((token, "drawing text"))
    for value, source in candidates:
        family = _canonical_material_family(value)
        key = str(family or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        if str(family).upper() == str(material or "").upper():
            continue
        if config.material_has_a_rate(family):
            return family, {
                "arbitrated_material": material,
                "priced_material": family,
                "priced_material_source": source,
                "why": (f"{material} is not priceable by this engine -- no sheet rate and no "
                        f"GBP/kg -- and {family}, read from {source}, is. Priced from "
                        f"{family}. THE MATERIAL IS UNCONFIRMED: if the part really is "
                        f"{material}, this figure is wrong and the engine needs a rate for it."),
            }
    return material, None


_MARKET_INDICATION_CACHE: Dict[Tuple[str, Any], Any] = {}


def _market_cache_path(key: Tuple[str, Any]):
    """Where a looked-up sheet rate is kept between runs. None if nowhere is writable."""
    material, thickness = key
    safe = re.sub(r"[^A-Z0-9]+", "_", str(material).upper()).strip("_") or "UNKNOWN"
    try:
        gauge = f"{float(thickness):g}" if thickness else "nogauge"
    except (TypeError, ValueError):
        gauge = "nogauge"
    try:
        base = Path(getattr(config, "BASE_DIR", None) or Path(__file__).resolve().parents[1])
    except Exception:                                        # noqa: BLE001
        return None
    return base / "cache" / "market_sheet_rates" / f"{safe}__{gauge}mm.json"


def market_indication_for(part: Dict[str, Any], material: Any) -> Optional[Dict[str, Any]]:
    """A market sheet price for a material this engine holds no rate for. NEVER a rate.

    THE ENGINE MUST NOT BE THE REASON A NUMBER DOES NOT EXIST. config carries no rate for
    ABS, PETG, PVC, FOAMEX, PP or PS, and is right not to: "a price is a commercial fact and
    SDI owns it; inventing one would put a number on a quote that nobody has agreed to."
    But declining to INVENT a rate is not the same as declining to LOOK ONE UP, and treating
    those as the same thing is why 11650-01-05A DOOR showed GBP 0.00 with nobody told why.

    What comes back is an AI/web estimate: not reproducible, not firm, and it does not enter
    a total on any path. It exists so the line an estimator has to rule on carries a number
    and a source instead of a blank -- the same standard as every other candidate this engine
    surfaces. Off by the same switch as the bought-in fallback, and bounded by the same
    per-job budget, because it is the same lookup.
    """
    if os.environ.get("SDI_OFFLINE"):
        return None
    policy = getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}
    if not policy.get("enable_web_ai_fallback"):
        return None
    try:
        from web_ai_price_lookup import market_sheet_rate_indication
    except Exception:                                        # noqa: BLE001
        return None
    sheet = (getattr(config, "STANDARD_SHEET_SIZES_MM", {}) or {}).get(
        str(material or "").strip().upper())
    sheet_l, sheet_w = (sheet[-1] if sheet else (None, None))
    # ONE CALL PER MATERIAL AND GAUGE, ACROSS JOBS AND NOT JUST WITHIN ONE. A job with six
    # ABS panels asked six times for the same sheet rate -- six round trips for one answer,
    # and six chances to return six different numbers for the same material. In-process
    # memoisation fixes that for one run; the next run pays again, and can disagree with the
    # last one about what a job's material costs. A sheet rate is not a per-run fact.
    #
    # On disk beside the vision-BOM cache, under config.BASE_DIR, for the reason written
    # there: a hardcoded path means every re-run on another machine pays again and silently
    # gets nothing when the drive is absent.
    key = (str(material or "").strip().upper(), _safe_thickness_mm(part))
    if key in _MARKET_INDICATION_CACHE:
        return _MARKET_INDICATION_CACHE[key]
    _disk = _market_cache_path(key)
    if _disk is not None and _disk.exists():
        try:
            _held = json.loads(_disk.read_text(encoding="utf-8"))
            _MARKET_INDICATION_CACHE[key] = _held or None
            return _MARKET_INDICATION_CACHE[key]
        except Exception:                                    # noqa: BLE001
            pass                                             # a corrupt cache is not an answer
    try:
        found = market_sheet_rate_indication(
            material, _safe_thickness_mm(part), sheet_l, sheet_w)
    except Exception:                                        # noqa: BLE001
        found = None
    _MARKET_INDICATION_CACHE[key] = found
    # A MISS IS NOT CACHED. A failed lookup is usually a network or credit problem, not a
    # fact about the material -- writing it down would make one bad afternoon permanent.
    if found and _disk is not None:
        try:
            _disk.parent.mkdir(parents=True, exist_ok=True)
            _disk.write_text(json.dumps(dict(found, material=key[0], cached_on=str(
                __import__("datetime").date.today())), indent=1), encoding="utf-8")
        except Exception:                                    # noqa: BLE001
            pass
    return found


def _price_declared_material_layers(part: Dict[str, Any],
                                    material: Dict[str, Any]) -> Dict[str, Any]:
    """A laminated part is MORE THAN ONE MATERIAL, and every layer has to reach the price.

    JAE827 on 0359342 is "Flexi MDF 6mm and 9mm" — a curved corner laminated from two
    boards over R49. The part record holds ONE material and ONE thickness, so the engine
    could only ever price one of them, and when I wrote that part's assumption into the
    confirmations file I priced the 9mm and said in the note that the 6mm was excluded.
    Writing the omission down does not make it a decision; it only makes it explicit that
    money was left out. An explanation must never legitimise an exclusion.

    So a part may declare its layers, and each is priced THROUGH THIS SAME FUNCTION — the
    layer becomes a shadow part carrying its own material, gauge and blank, and goes down
    the identical route. No new rate, no new price model, nothing invented: whatever the
    engine would charge for that board as a part in its own right is what the layer costs.

    NO NEW IDENTITY IS MINTED. The layers stay ON the part, because a lamination is one
    component with several materials, not several components — turning each into a part
    would double the fasteners, the handling and the assembly around it, which is the exact
    failure the canonical population exists to prevent.

    The bonding, pressing and forming labour is NOT added here — the engine has no model
    for it — and the part says so rather than letting a material-only figure read as
    complete.
    """
    layers = part.get("material_layers") or []
    if not isinstance(layers, list) or len(layers) < 2 or not isinstance(material, dict):
        return material

    # THE PRIMARY LAYER IS CHECKED, NOT ASSUMED. The ordinary material calculation prices
    # the part's own material and gauge, and layers[0] is only the same thing while nothing
    # has moved them. CAD precedence can: a DXF arriving with its own gauge displaces the
    # confirmed figure by design, and then the "primary" being counted as layer 1 is a
    # different board from the one declared — one layer priced twice, another not at all,
    # and every count still adding up.
    primary_declared = layers[0] if isinstance(layers[0], dict) else {}
    primary_matches = (
        str(primary_declared.get("material") or "").strip().upper()
        == str(part.get("normalized_material") or "").strip().upper()
        and _safe_float(primary_declared.get("thickness_mm"))
        == _safe_float(part.get("normalized_thickness_mm")))

    priced: List[Dict[str, Any]] = []
    added = 0.0
    for index, layer in enumerate(layers[1:], start=2):
        if not isinstance(layer, dict):
            continue
        shadow = {
            "part_number": f"{part.get('part_number')} layer {index}",
            "description": str(layer.get("note") or part.get("description") or ""),
            "quantity": part.get("quantity"),
            "normalized_material": layer.get("material") or part.get("normalized_material"),
            "normalized_thickness_mm": layer.get("thickness_mm"),
            "blank_length_mm": layer.get("blank_length_mm") or part.get("blank_length_mm"),
            "blank_width_mm": layer.get("blank_width_mm") or part.get("blank_width_mm"),
            "review_flags": [],
        }
        layer_cost = estimate_material(shadow)
        unit = _safe_float((layer_cost or {}).get("unit_material_cost_gbp"))
        # AN OUTCOME, NOT A RECORD. The first version appended an entry whichever way the
        # pricing went and substituted 0.0 for a miss, so a layer that priced NOTHING still
        # counted as one of N — and the check that asks "did every layer reach the price?"
        # answered yes by counting the failures. A board that cost nothing was not bought.
        ok = bool(unit and unit > 0)
        added += unit or 0.0
        priced.append({
            "layer": index,
            "material": shadow["normalized_material"],
            "thickness_mm": shadow["normalized_thickness_mm"],
            "blank_length_mm": shadow["blank_length_mm"],
            "blank_width_mm": shadow["blank_width_mm"],
            "unit_material_cost_gbp": round(unit or 0.0, 4),
            "priced": ok,
            "cost_method": (layer_cost or {}).get("cost_method"),
            "note": layer.get("note"),
        })
        if not ok:
            part.setdefault("review_flags", []).append(
                f"{part.get('part_number')} layer {index} "
                f"({shadow['normalized_material']} {shadow['normalized_thickness_mm']}mm) "
                f"returned NO price — it is a board this part is built from and it is "
                f"currently costing nothing. Name a rate for that material")

    if not priced:
        return material

    base = _safe_float(material.get("unit_material_cost_gbp")) or 0.0
    material = dict(material)
    material["unit_material_cost_gbp"] = round(base + added, 4)
    material["material_layers_priced"] = priced
    material["material_layers_added_gbp"] = round(added, 4)
    material["material_layers_primary_matches"] = primary_matches
    # AND THE HONEST LIMIT OF THIS CHANGE, RECORDED AS DATA RATHER THAN LEFT TO BE DISCOVERED.
    #
    # This helper raises unit_material_cost_gbp, and the Other Sheet / Sheet Steel writers do
    # not read it: they take material_estimate.sheet_price_gbp and let the WORKBOOK recompute
    # cost-per-part from sheet price over parts-per-sheet. unit_material_cost_gbp is only
    # their FALLBACK when no sheet price exists. So on the ordinary board path the extra
    # layer's money is computed here and then dropped on the way to the sheet the customer is
    # quoted from — the arithmetic is right and the workbook is unchanged.
    #
    # A second board is a second sheet consumption and needs its own workbook ROW. Until that
    # writer exists this stays False and the BLOCKING invariant refuses the job, because the
    # one thing worse than a missing layer is a missing layer that reports CLEAR.
    material["material_layers_reach_workbook"] = False
    _qty = _safe_float(part.get("quantity")) or 1.0
    if material.get("extended_material_cost_gbp") is not None:
        material["extended_material_cost_gbp"] = round(
            (base + added) * _qty, 4)

    part.setdefault("review_flags", []).append(
        f"{part.get('part_number')} is laminated from {len(priced) + 1} layers: "
        + "; ".join(f"layer {p['layer']} {p['material']} {p['thickness_mm']}mm "
                    f"£{p['unit_material_cost_gbp']:.2f}" for p in priced)
        + f" added to the primary layer's £{base:.2f}. The BONDING / PRESSING / FORMING "
          f"labour for laminating them is NOT in this figure — the engine has no model for "
          f"it — so add it before issue")
    return material


_ROLL_GOODS_WORDS = ("TAPE", "VINYL", "FOAM STRIP", "FELT STRIP", "REEL", "WEBBING")
_ROLL_LENGTH_RE = re.compile(r"LENGTH\s*[:=]\s*([\d.]+)", re.IGNORECASE)


def roll_goods_material(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Price a length off a roll, or say why it cannot be. None if this is not roll goods.

    A PIECE COUNT MUST NEVER MULTIPLY A PACK PRICE. 0355255's tape was costed 3 x a per-each
    default rate and came to £13.63 where the length used makes it 28p — on a unit whose whole
    manual estimate is £7.63. The record knew enough all along: its description carries
    "LENGTH: 200.00" and its quantity is 3. What it lacked was the roll's own length and price,
    which is a buying fact and now lives in config.ROLL_GOODS_CATALOGUE.

    Returns a material estimate priced by consumed length when the code is in that table, and a
    WITHHELD one naming the arithmetic when it is not. Never a per-each guess.
    """
    _blob = " ".join(str(part.get(k) or "") for k in ("part_number", "description")).upper()
    if not any(w in _blob for w in _ROLL_GOODS_WORDS):
        return None

    # MATCHED WITH THE SPACES AND HYPHENS TAKEN OUT, because one code is written three ways in
    # a single pack: 0355255's own line reads "TAPE 113C" where the catalogue says "TAPE113C",
    # and a straight substring test misses it — which is a silent miss, priced as an each.
    _table = getattr(config, "ROLL_GOODS_CATALOGUE", {}) or {}
    _squashed = re.sub(r"[^A-Z0-9]", "", _blob)
    _entry, _code = None, ""
    for _c, _e in _table.items():
        if re.sub(r"[^A-Z0-9]", "", str(_c).upper()) in _squashed:
            _entry, _code = _e, str(_c).upper()
            break

    _qty = _safe_int(part.get("quantity")) or 1
    _m = _ROLL_LENGTH_RE.search(_blob)
    _piece_mm = _safe_float(_m.group(1)) if _m else _safe_float(part.get("overall_length_mm"))
    # A PERSON'S CONFIRMED LENGTH OUTRANKS THE DESCRIPTION PARSE — the pack can state the
    # length twice with different figures (10975: 200 against 220), and the estimator's
    # pick is the answer, stamped once, not re-litigated per run.
    _conf_mm = _safe_float(part.get("confirmed_piece_length_mm"))
    if _conf_mm:
        if _piece_mm and abs(_conf_mm - _piece_mm) > 0.5:
            part.setdefault("review_flags", []).append(
                f"ROLL GOODS: piece length {_conf_mm:g} mm confirmed by an estimator, "
                f"over the description's {_piece_mm:g} mm")
        _piece_mm = _conf_mm
    _used_mm = (_piece_mm or 0) * _qty

    if not _entry or not _used_mm:
        _why = ("the length of each piece is not stated" if not _used_mm
                else f"{_code or 'this code'} is not in the roll-goods catalogue, so the roll "
                     f"length and roll price are not known")
        part.setdefault("review_flags", []).append(
            f"ROLL GOODS: NOT PRICED. This is sold off a roll and the drawing asks for pieces "
            f"cut from one — a piece count must never multiply a pack price, which is how "
            f"0355255's tape reached £13.63 against 28p. Withheld because {_why}. Give the "
            f"roll length and roll price (and the piece length if it is not on the drawing) "
            f"and it prices as length used ÷ roll length × roll price")
        return {"material": part.get("normalized_material"), "thickness_mm": None,
                "blank_length_mm": None, "blank_width_mm": None, "blank_area_m2": None,
                "unit_material_mass_kg": None, "unit_material_cost_gbp": None,
                "cost_per_part_gbp": None, "extended_material_cost_gbp": None,
                "stock_estimate": None, "stock_form": "roll",
                "requires_flat_blank": False,
                "cost_method": "roll_goods_withheld_estimator_to_price",
                "price_source": {"schema": "price_source.v1",
                                 "source": "roll_goods_withheld",
                                 "source_name": "roll_goods_withheld",
                                 "applied": False, "affects_total": False}}

    # THE LENGTH IS A PACKAGING FACT; THE PRICE IS MONEY AND IS ASKED FOR.
    #
    # James: "we can't hard code prices. we can log hourly throughput rates but we need to
    # start understanding if these change and why." roll_price_gbp used to sit in the
    # catalogue beside the length — a price in source control, which cannot go stale visibly
    # and tells nobody when it moves.
    #
    # So SDI's own priced sources are asked first (part system cost, UDEF, historical
    # quotes, supplier catalogue), and the estimator's stated figure answers only where they
    # cannot. Where both answer and disagree, the line carries BOTH — because which of them
    # is right is not a question this engine can settle, and choosing silently is how it
    # stops being asked.
    _roll_mm = _safe_float(_entry.get("roll_length_mm")) or 0.0
    try:
        from stated_prices import resolve as _resolve_price
        _px = _resolve_price(_code, part.get("description"))
    except Exception:                                                # noqa: BLE001
        _px = {"gbp": None, "basis": None, "label": "", "disagreement": None}
    _roll_gbp = _safe_float(_px.get("gbp")) or 0.0
    if _roll_mm <= 0 or _roll_gbp <= 0:
        part.setdefault("review_flags", []).append(
            f"ROLL GOODS {_code}: NOT PRICED. The roll is {_roll_mm:g} mm, which we hold, "
            f"but nothing priced it — neither SDI's own system cost nor a figure an "
            f"estimator has stated. Give the roll price and it costs as length used ÷ roll "
            f"length × roll price.")
        return {"material": part.get("normalized_material"), "thickness_mm": None,
                "blank_length_mm": None, "blank_width_mm": None, "blank_area_m2": None,
                "unit_material_mass_kg": None, "unit_material_cost_gbp": None,
                "cost_per_part_gbp": None, "extended_material_cost_gbp": None,
                "stock_estimate": None, "stock_form": "roll", "requires_flat_blank": False,
                "cost_method": "roll_goods_withheld_estimator_to_price",
                "price_source": {"schema": "price_source.v1",
                                 "source": "roll_goods_withheld",
                                 "source_name": "roll_goods_withheld",
                                 "applied": False, "affects_total": False}}
    if _px.get("disagreement"):
        part.setdefault("review_flags", []).append(
            f"PRICE DISAGREEMENT — {_px['disagreement']}. Priced on the system figure; "
            f"confirm which stands.")
    # PER PIECE AND PER LINE ARE DIFFERENT NUMBERS, AND THE SHEET MULTIPLIES ONE OF THEM.
    #
    # This returned the LINE cost in the per-part field, and the Estimate's own BOM formula
    # multiplies the price column by Qty Per Unit. So 0355255's tape went out as
    #
    #     price 0.27   qty 3   total 0.8424
    #
    # — three lots of the whole 600 mm, 1,800 mm of tape against Howard's 28p. The function's
    # own docstring says a piece count must never multiply a pack price; it then handed the
    # sheet a LINE price for the sheet to multiply by the piece count, which is the same
    # error one level along.
    _piece_cost = round((_piece_mm or 0) / _roll_mm * _roll_gbp, 4)
    _cost = round(_used_mm / _roll_mm * _roll_gbp, 4)
    part.setdefault("review_flags", []).append(
        f"ROLL GOODS {_code}: {_piece_mm:g} mm a piece at £{_piece_cost:.2f}; {_qty} x "
        f"{_piece_mm:g} mm = {_used_mm:g} mm of a {_roll_mm:g} mm roll at £{_roll_gbp:.2f} "
        f"= £{_cost:.2f} for the line — priced by the length used, not by the piece. "
        f"Roll length: {_entry.get('source') or 'config'}. "
        f"Roll price: {_px.get('label') or 'source not named'}")
    # THE OLD ANSWER COMES OFF THE MONEY BEFORE THE NEW ONE GOES ON. 10975's tape record
    # still carried an abandoned LLM answer from an earlier pricing pass, stamped as
    # applied — so price_not_reproducible BLOCKED the job for a £13.63 that never reached
    # the total, while the £0.28 that did was the roll arithmetic below. Every stamp
    # already on the part is a rival this price has just displaced; say so on each.
    try:
        from price_provenance import mark_withheld as _mark_withheld
        _mark_withheld(part, reason="superseded — this line is priced by the roll-goods "
                                    "length arithmetic; this earlier figure does not "
                                    "reach the total")
    except Exception:                                                # noqa: BLE001
        pass
    return {"material": part.get("normalized_material"), "thickness_mm": None,
            "blank_length_mm": _piece_mm, "blank_width_mm": None, "blank_area_m2": None,
            "unit_material_mass_kg": None,
            # PER PIECE in the per-part fields, the LINE total in the extended one — which is
            # what those two field names have always meant everywhere else, and the sheet
            # relies on: extended = per part x qty, and it does that multiplication itself.
            "unit_material_cost_gbp": _piece_cost, "cost_per_part_gbp": _piece_cost,
            "extended_material_cost_gbp": _cost,
            "stock_estimate": None, "stock_form": "roll", "requires_flat_blank": False,
            "cost_method": "roll_goods_by_length",
            "roll_length_mm": _roll_mm, "roll_price_gbp": _roll_gbp,
            "length_used_mm": _used_mm,
            # THE STAMP CARRIES WHICH SOURCE ANSWERED, not the shape of the calculation.
            # It said "roll_goods_catalogue" whichever way the price arrived, so Howard's
            # stated GBP 4.50 classified as `catalogue` and rendered on the sheet exactly
            # like a row purchasing buys against. The basis resolve() returned is the fact;
            # the label is the sentence an estimator reads beside it.
            # A STAMP THE WALKER CAN SEE. iter_price_stamps recognises a block by the
            # schema marker or by carrying `source_name` — this one had only `source`, so
            # every consumer that walks the record for its prices (the supplier column, the
            # reproducibility check, the provenance listing) walked straight past the stamp
            # that put the money on, and labelled the line from whatever OTHER stamp was
            # lying around. On 10975 that was an abandoned LLM answer: £0.09 of UDEF roll
            # arithmetic wearing "xAI Grok LLM - INDICATIVE, NOT A QUOTE".
            #
            # source_name carries the MACHINE name, never the label sentence:
            # classify_price_source classifies on it, and a sentence classifies as
            # `catalogue` by default — the exact mislabelling this stamp exists to end.
            "price_source": {"schema": "price_source.v1",
                             "source": _roll_source_name(_px),
                             "source_name": _roll_source_name(_px),
                             "applied": True, "affects_total": True,
                             "price_label": _px.get("label") or None,
                             "roll_length_source": _entry.get("source"),
                             "provenance": _entry.get("source")}}


def _roll_source_name(px: Dict[str, Any]) -> str:
    """The machine name of whatever priced the roll, for the stamp."""
    if px.get("basis") == "estimator_stated":
        return "estimator_stated"
    return str(px.get("source") or "roll_goods_priced")


def estimate_material(part: Dict[str, Any]) -> Dict[str, Any]:
    # BEFORE ANY PER-EACH OR PER-KILO RATE. A thing sold off a roll is priced by the length
    # taken off it; everything below this line prices a blank, a weight or an each, and all
    # three are the wrong unit for a strip of tape.
    _roll = roll_goods_material(part)
    if _roll is not None:
        return _roll

    material = part.get("normalized_material") or _first(part.get("materials", []))

    # A CROSS-REFERENCE IS NOT A MATERIAL.
    #
    # A GA puts "REFER TO INDIVIDUAL COMPONENT DRAWINGS" in its MATERIAL field when the real
    # values live on the component sheets. On 10575-02 the engine stored that string as the
    # material: nothing could be priced against it, so the part costed £0.00, and the same string
    # in the FINISH field meant no finish was ever routed — £0.00 of powder and £0.00 of P.Coat
    # labour on a powder-coated job. Nothing failed; the job was costed as though the parts were
    # made of nothing.
    #
    # The guard existed on the title-block reader already. This value came from llm_full_extract,
    # which had none. Cleared here, at the point every material passes through, and flagged —
    # because "we were not told" and "no material needed" must not look the same on a sheet.
    try:
        from extractor_patterns import is_cross_reference_note as _is_xref
    except Exception:                                        # noqa: BLE001
        _is_xref = lambda _v: False                          # noqa: E731
    if _is_xref(material):
        part.setdefault("review_flags", []).append(
            f"material not stated on this drawing — it reads {str(material)!r}, which defers to "
            f"another sheet. That sheet is not in this pack, so this part has NO material and "
            f"cannot be priced. An estimator must supply it.")
        part["normalized_material"] = None   # precedence: direct-write ok — removes a non-answer, adds no evidence. The arbitration weighs competing MATERIALS; "refer to another drawing" is not a competing material and there is nothing to weigh it against. Submitting it as a reading would give a cross-reference a rank and let it beat a real one.
        material = None

    # THE COLLAPSE LOSES THE FACING, SO THE FACING IS KEPT BESIDE IT. "MFMDF" contains
    # "MDF" and canonicalises to plain MDF — right for block routing, and it silently
    # discards the one word that says the board is bought pre-faced. A drawing that STATES
    # the faced family must not need laminate evidence found elsewhere on the sheet, and
    # a scoped rate measured on faced board must be able to see that this IS faced board.
    _u_facing = str(material or "").upper().replace("_", " ")
    if "MFMDF" in _u_facing or ("MELAMINE" in _u_facing and "MDF" in _u_facing):
        part["_stated_faced_family"] = "MFMDF"
    elif re.search(r"\bMFC\b", _u_facing) or ("MELAMINE" in _u_facing
                                              and "CHIPBOARD" in _u_facing):
        part["_stated_faced_family"] = "MFC"
    material = _canonical_material_family(material)
    if material:
        # Propagate the canonical family back onto the part so wb_populate's block routing
        # (which reads normalized_material) sends timber/board to the right block, not steel.
        # NORMALISATION, not new evidence: this is the part's OWN material rewritten to its
        # canonical family name ("MR MDF" -> "MDF"). It must not lose the source that
        # supplied it, so the recorded source is carried through unchanged rather than
        # re-stamped as if the estimator had observed something.
        part["normalized_material"] = material   # precedence: direct-write ok — canonicalises the part's own value, source unchanged
    # AFTER THE CANONICAL WRITE-BACK, DELIBERATELY. That line propagates the part's OWN
    # material to wb_populate's block routing. Substituting before it meant the rescue
    # material was written to normalized_material as well, so the arbitration's answer was
    # silently replaced by the reading that merely happened to have a rate -- exactly what
    # this rule promises not to do. From here on `material` is the PRICING material only.
    _arbitrated_material = material
    material, _material_conflict = _material_we_can_actually_price(part, material)
    # ASKED WHETHER OR NOT A SUBSTITUTION RESCUED THE PRICE. Where nothing rescued it, this
    # is the only number on the line. Where something did, it is how an estimator judges
    # whether the substitution matters: if ABS and POLYCARBONATE come back at similar money,
    # the conflict is commercially small and the ruling is easy. It never enters a total on
    # either path -- it is an AI/web estimate, and this engine does not sum those.
    if not config.material_has_a_rate(_arbitrated_material):
        _indication = market_indication_for(part, _arbitrated_material)
        if _indication:
            part["material_market_indication"] = dict(_indication,
                                                      material=_arbitrated_material)
            # .get, NOT [..]. A lookup that returns a partial dict must not take the run
            # down inside the line that explains it -- and it did, on a dict with no
            # "source" key. The message is the least important thing in this function and
            # was the only thing that could raise.
            # WHAT ACTUALLY HAPPENED, NOT WHAT THIS BLOCK IS FOR. When a substitution rescued
            # the price, the line below is NOT what the line was costed from -- the pricing
            # material has a rate, so _llm_rate_m2 stays None and the market figure never
            # reaches the arithmetic. Saying "PRICED FROM IT" on both paths put a false
            # statement on the console directly above the message contradicting it: 11650's
            # 11650-01-05A read "PRICED FROM IT" and then "Priced from POLYCARBONATE".
            # A console that asserts a decision the code did not take is worse than a silent
            # one, because it is believed.
            _priced_from_it = _material_conflict is None
            print(f"   [material] {part.get('part_number')}: no rate for "
                  f"{_arbitrated_material}; market indication "
                  f"£{_safe_float(_indication.get('gbp_per_m2')) or 0.0:.2f}/m2 "
                  f"(£{_safe_float(_indication.get('gbp_per_sheet')) or 0.0:.2f}/sheet, "
                  f"{_indication.get('source') or 'llm'}) "
                  + (f"— PRICED FROM IT, marked as an LLM estimate. Not a supplier quote; "
                     f"this job cannot go out firm on it."
                     if _priced_from_it else
                     f"— FOR COMPARISON ONLY. This line is costed from "
                     f"{_material_conflict.get('priced_material') or 'the substitute below'}, not "
                     f"from this figure. Compare the two: if they are close the substitution "
                     f"barely matters, if they are far apart it decides the price."),
                  flush=True)
    if _material_conflict:
        part["material_priced_as"] = _material_conflict
        part.setdefault("review_flags", []).append({
            "severity": "warning", "flag": "material_unpriceable_substituted",
            "detail": _material_conflict["why"],
        })
        print(f"   [material] {part.get('part_number')}: {_material_conflict['why']}", flush=True)
    thickness = _safe_thickness_mm(part)
    quantity = _safe_int(part.get("quantity")) or 1
    dims = infer_primary_dimensions(part)
    blank_length, blank_width = estimate_blank_size(dims)
    blank_length, blank_width = _blank_that_could_have_been_cut(
        part, blank_length, blank_width)

    # FIX 2 (general): a weldment/assembly PARENT part is a roll-up of child parts that
    # are themselves in the BOM and individually material-costed. Giving the parent its
    # own blank double-counts material (e.g. 1455-C-101 HEADER WELDMENT carried £7.48 on
    # top of its already-costed children 1455-C-001..005). Convention matches Tim: the
    # parent line is LABOUR-only (weld/assemble). Config-driven token list, no per-job logic.
    _desc_wm = str(part.get("description") or "").upper()
    _wm_tokens = getattr(config, "WELDMENT_PARENT_DESC_TOKENS",
                         ["WELDMENT", "WELD ASSEMBLY", "WELDED ASSEMBLY", "WELD ASSY"])
    # Weld-assembly parent by PART NUMBER (e.g. ...-WA01 / ...-SA01) when it carries
    # no flat DXF of its own. This is spelling-independent, so a mislabelled title
    # block (material "MDF", a "SELDED" typo) cannot misroute the parent's material:
    # it is suppressed and carried by the costed child detail parts.
    _pn_wm = str(part.get("part_number") or "").upper()
    _wm_suffixes = getattr(config, "WELDMENT_PARENT_PN_SUFFIXES", [r"-WA\d*$", r"-SA\d*$"])
    _has_own_flat = ("dxf" in str(part.get("geometry_source") or "").lower()
                     or _has_native_flat(part))
    # is_assembly_parent is stamped upstream (drawing_job_merge) for a part with no
    # flat DXF whose PN is a strict prefix of >=2 others — a roll-up whose material
    # is carried by its costed children (TANK 04 over 04-01/04-02).
    # THE GA BOM HIERARCHY IS AN AUTHORITY ON WHAT IS AN ASSEMBLY.
    #
    # The whole-document extract already returns `assemblies` -- parent part numbers with
    # their children -- and llm_full_job stamps every match is_sub_assembly. pricing_service
    # reads that field. NOTHING IN THE ESTIMATOR DID: both suppressions here and in
    # estimate_part keyed on is_assembly_parent, a different name for the same idea.
    #
    # So 12120-01-103 SCREEN MOUNTING BRACKET, correctly identified as a sub-assembly from
    # the GA tree, was still given sheet material, a laser and a fold -- because its
    # description carries no assembly token, its children (01M, 06M) are siblings rather
    # than prefixed, and it does not match the ...-0*-... GA pattern. Every parent detector
    # missed it while the answer sat on the record under the other name.
    #
    # Guarded on _has_own_flat: a real flat pattern is MEASURED evidence the part is a
    # fabricated leaf, and measurement outranks a transcribed hierarchy (dxf 80 >
    # llm_full_extract 40). Where they disagree the geometry wins and the part stays a leaf.
    _sub_asm_by_bom = bool(part.get("is_sub_assembly")) and not _has_own_flat
    # THE FIFTH SPELLING. The canonical graph reaches its own conclusion and stamps it as
    # canonical_kind; this test knew four field names and not that one. Asked through the
    # shared predicate so there is one definition of "this is a parent" rather than a copy
    # per pass — the exact defect the comment above records, one name later.
    #
    # Unioned, never substituted: this can only recognise MORE parents than before, and the
    # failure direction it guards is a parent charged as a leaf, which books material and
    # fabrication twice. Still gated on _has_own_flat below for the hierarchy-only signals,
    # because a measured flat outranks a transcribed tree.
    try:
        import bought_in_policy as _bip
        _canonical_parent = (_bip.is_assembly(part) and not _has_own_flat)
    except Exception:
        _canonical_parent = False
    _is_weldment_parent = (
        any(_t in _desc_wm for _t in _wm_tokens)
        or (not _has_own_flat and any(re.search(_sfx, _pn_wm) for _sfx in _wm_suffixes))
        or bool(part.get("is_assembly_parent"))
        or _sub_asm_by_bom
        or _canonical_parent
    )
    if _is_weldment_parent:
        # ONE PARENT TEST, NOT TWO THAT DISAGREE.
        #
        # This concludes "parent" from three signals; the phantom-fab strip in estimate_part
        # reads only part["is_assembly_parent"], which is stamped upstream by a rule needing
        # the PN to be a strict prefix of >=2 others. A sub-assembly whose constituents are
        # SIBLINGS -- 12120-01-101 STAND WELD ASSY, built from 12120-01-02M and -03M -- has
        # no prefix children at all, so that rule cannot fire.
        #
        # The result was a parent recognised HERE by its description, correctly carrying no
        # material, while still billing a laser and a fold read off the assembly drawing's
        # linework: 101 came out at GBP 0.00 material with GBP 1.92 laser and GBP 0.01 fold.
        # Suppressed on one axis and not the other, from the same conclusion.
        #
        # Record the conclusion where the strip can see it. Assembly ops (weld, dress,
        # powder, assemble) are deliberately left alone -- welding the parent IS the work.
        if not part.get("is_assembly_parent"):
            part["is_assembly_parent"] = True
            part.setdefault("review_flags", []).append(
                "weldment/assembly parent recognised by description or PN suffix — "
                "material carried by children AND geometry-derived fabrication "
                "(laser/fold/punch) suppressed; assembly ops retained")
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": None,
            "blank_width_mm": None,
            "blank_area_m2": None,
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": 0.0,
            "cost_per_part_gbp": 0.0,
            "extended_sheet_material_cost_gbp": 0.0,
            "powder_consumable": None,
            "extended_material_cost_gbp": 0.0,
            "stock_estimate": {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None},
            "cost_method": "weldment_parent_material_in_children",
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "reliability_flags": ["weldment_parent_material_suppressed"],
            "note": "Weldment/assembly parent \u2014 material carried by child BOM lines; parent costed for labour only.",
            "price_source": _build_price_source_metadata(
                {}, fallback_source="weldment_parent_material_in_children",
                applied=False, applied_basis=None,
            ),
        }

    # Acrylic / plastic sheet is bought and costed by the SHEET, not by mass — the £/kg
    # path under-prices it (a panel ~£1.98 by mass vs ~£3.20 sheet-nested). Price it
    # sheet-nested from config.ACRYLIC_SHEET_PRICE_GBP (PROVISIONAL, pending estimating),
    # using the existing nesting formula with the acrylic sheet size. Gated strictly to
    # acrylic-like materials, so steel / wire / MDF / 1282 are untouched.
    _mat_acr = str(material or "").upper().replace("_", " ")
    # A MATERIAL WITH NO RATE IS NOT A MATERIAL WITH NO COST. Where config holds no rate and
    # the market lookup returned a sheet price, that price goes through the SAME area x GBP/m2
    # arithmetic the acrylic family uses -- one calculation, not a second copy of it. The
    # figure is stamped as an LLM market estimate, so check_prices_are_firm sees it, the job
    # can never be released as firm on it, and it is visible for what it is on every report.
    _llm_ind = part.get("material_market_indication") or {}
    _llm_rate_m2 = None
    if not config.material_has_a_rate(material):
        try:
            _llm_rate_m2 = float(_llm_ind.get("gbp_per_m2") or 0.0) or None
        except (TypeError, ValueError):
            _llm_rate_m2 = None
    # THE CATALOGUE RATE IS RESOLVED BEFORE THE GATE, BECAUSE IT IS PART OF THE GATE.
    #
    # This branch was entered only for a handful of named plastics or when an LLM had
    # already returned a GBP/m2 -- so a material with a REAL rate sitting in UDEF could not
    # reach the code that would have used it unless a language model happened to guess a
    # price for it first. On 11650-04 that is exactly what happened: the two base panels got
    # in on an LLM rate and their handed twins, which got none, fell through to no_price and
    # were costed at ZERO. Two of four panels free, and the job's material fell from GBP
    # 76.66 to 9.36.
    #
    # A live catalogue rate is the strongest reason to enter this branch that exists. It is
    # cached per material and gauge, so asking early costs one lookup per pair, not one per
    # part.
    # ── THE BOARD IS PROMOTED BEFORE ANY CATALOGUE IS ASKED ─────────────────────────
    #
    # THE FACED-BOARD PROMOTION WAS UNREACHABLE ON EVERY JOB THAT HAD A CORE RATE.
    #
    # It lives four hundred lines below, under "FACED BOARD: PRICED BY THE SHEET", and
    # its rule is written there: once promoted a part may NOT fall back to the bare
    # core's money. That was enforced against the £/kg path and against nothing else.
    # The line immediately below asks the live UDEF catalogue for a £/m² on the material
    # as read — and the catalogue has plain 9mm MDF — so the branch that follows PRICED
    # THE PART AND RETURNED, and the promotion never ran at all.
    #
    # 11908-21 is what that costs, in Tony Ford's own words: a laminated tray costed as
    # raw MDF at £43.12 on a 3050 x 1525 sheet, when the board is bought pre-faced at
    # 3080 x 1220. And because `_laminate_in_board` is stamped by the promotion, the
    # whole faced-board pilot downstream went with it — the scoped joinery rates his
    # review supplied (bench, packing, edge banding) never saw a faced-board job, so the
    # sheet ran on the unmeasured department guesses he had just corrected. One
    # unreachable branch, and four of his findings.
    #
    # So the question is asked HERE, once, in front of every pricing path, and the
    # catalogue is asked about the board SDI actually buys. A faced family with a live
    # rate is the best answer this engine can give — rung 1, current, checkable. A faced
    # family with none must not be handed the core's rate instead: it falls through to
    # the faced block below and reaches the sheet as a visible unpriced line.
    _faced_family, _faced_why = _faced_board_promotion(part, material)
    if _faced_family:
        part["_laminate_in_board"] = True
        part["_faced_board_family"] = _faced_family
        part.setdefault("review_flags", []).append(
            f"{material} + LAMINATED is bought pre-faced as {_faced_family} — evidence: "
            f"{_faced_why}. The laminating on the route is IN the sheet price, not a "
            f"shop operation.")
    _cost_family = _faced_family or material
    _live_sheet_rate = _resolve_board_sheet_rate_gbp_per_m2(_cost_family, thickness)
    if ((_mat_acr in config.PLASTIC_SHEET_PRICED_MATERIALS or _llm_rate_m2 or _live_sheet_rate)
            and blank_length and blank_width
            # A promoted board with no rate of its own does not borrow the core's.
            and not (_faced_family and not _live_sheet_rate)):
        _acr_area_m2 = (float(blank_length) * float(blank_width)) / 1_000_000.0
        _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))

        # Priced by area x a LIVE GBP/m2 from the current UDEF catalogue (plain stock at this
        # gauge). Tracks price changes automatically -- no stale config table. Falls through
        # to the acrylic-config path if the catalogue holds nothing for this material.
        _hips_rate = _live_sheet_rate
        if _hips_rate and _hips_rate.get("rate_gbp_per_m2"):
            _rate_m2 = float(_hips_rate["rate_gbp_per_m2"])
            _hips_cost_part = round(_acr_area_m2 * _rate_m2 * (1.0 + _scrap), 2)
            _hips_ext = round(_hips_cost_part * quantity, 2)
            # THE OTHER SHEET BLOCK IS FILLED FROM `sheet_price_gbp` AND `parts_per_sheet`,
            # AND THIS BRANCH RETURNED NEITHER.
            #
            # While HIPS was the only material that could reach it nothing noticed. Opening
            # the gate to every sheet material sent 11650-04's ABS and PETG panels down here,
            # and the workbook said what it always would have:
            #
            #     Other-sheet 11650-04-01A-HANDED has no sheet price — Cost Per Part will be 0
            #
            # Two of four panels at zero, and the job's material fell from GBP 76.66 to 9.36.
            # The rate was correct; the shape handed to the sheet was not. A branch that
            # returns a cost the workbook cannot render has not priced anything.
            #
            # The sheet price is the RATE across a whole sheet -- the same arithmetic the
            # acrylic branch does -- and the nest comes from the one function that answers
            # "how many parts per sheet", so this cannot drift from the block it feeds.
            # NESTED ON THE SHEET THE MONEY BUYS. A promoted board is bought as the faced
            # family, and the faced family's stock sizes are not the core's: Tony's 9mm
            # laminated board comes 3080 x 1220, plain MDF 3050 x 1525. Nesting the rate on
            # the core's sheet is the same understatement as dividing one sheet's price by
            # another sheet's yield — it was his "wrong sheet size" finding.
            _hips_sheet_est = select_sheet_size(_cost_family, blank_length, blank_width,
                                                part=part)
            if (_hips_sheet_est or {}).get("rotated"):
                # THE BLANK IS WRITTEN TURNED, so the workbook's own fixed-orientation nest
                # reaches the better yield by its own arithmetic. Howard's 0355255 line 84:
                # 24/sheet as drawn, 26 with length and width exchanged.
                blank_length, blank_width = blank_width, blank_length
                part.setdefault("review_flags", []).append(
                    f"NESTED TURNED: {_hips_sheet_est.get('parts_per_sheet')}/sheet with the blank at "
                    f"{blank_length:g} x {blank_width:g} beats the drawn orientation — the "
                    f"sheet is written with the blank turned. Never done where the material or "
                    f"finish has a direction.")
            _hips_dims = _hips_sheet_est.get("candidate_sheet_size_mm") or [3050.0, 2050.0]
            _hips_sheet_area_m2 = (float(_hips_dims[0]) * float(_hips_dims[1])) / 1_000_000.0
            _hips_pps = _hips_sheet_est.get("parts_per_sheet")
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": round(_acr_area_m2, 4),
                "unit_material_mass_kg": None,
                "unit_material_cost_gbp": _hips_cost_part,
                "cost_per_part_gbp": _hips_cost_part,
                "extended_sheet_material_cost_gbp": _hips_ext,
                "powder_consumable": None,
                "extended_material_cost_gbp": _hips_ext,
                "stock_estimate": _hips_sheet_est,
                # PRICED BY AREA, RENDERED BY THE SHEET. The cost above is area x rate and
                # does not change; these let the Other Sheet row show the working the
                # estimators read -- a sheet price and a nest -- instead of a blank.
                "sheet_price_gbp": round(_rate_m2 * _hips_sheet_area_m2, 2),
                **({"parts_per_sheet": int(_hips_pps)} if _hips_pps else {}),
                "sheet_fraction_per_part": (round(_acr_area_m2 / _hips_sheet_area_m2, 6)
                                            if _hips_sheet_area_m2 else None),
                "nesting_rule": (_hips_sheet_est.get("nesting_rule")
                                 or _costed_facts.nesting_rule_for(_cost_family)),
                "cost_method": "sheet_rate_live_udef",
                # THE FAMILY THE MONEY WAS FOR. wb_populate's scoped joinery rates and the
                # workbook's block routing both read this; without it a promoted board
                # prices as faced and then runs on plain-MDF department rates.
                "costing_material_family": _cost_family,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "reliability_flags": [],
                "note": "%s sheet cost from LIVE UDEF rate £%.2f/m² (%s plain-stock sample(s) at %.1fmm) × %.4f m² area."
                        % (_hips_rate.get("material_token") or material, _rate_m2,
                           _hips_rate.get("sample_count"), _hips_rate.get("thickness_mm") or 0.0,
                           _acr_area_m2),
                "price_source": _build_price_source_metadata(
                    {}, fallback_source="sheet_rate_live_udef",
                    applied=True, applied_basis=(_hips_rate.get("basis")
                                                 or "udef_rate_gbp_per_m2_live"),
                ),
            }

        # Acrylic (and HIPS fallback): sheet-nested from config.ACRYLIC_SHEET_PRICE_GBP.
        # acrylic_area_pricing_v2 (2026-07-15): price the flat blank by AREA × £/m2 (UDEF-derived
        # Clear XT, PROVEN LINEAR full-sheet-to-blank), expressed through the workbook's own L/J so
        # estimators still read a real sheet price and parts-per-sheet. L = full-sheet price at the
        # £/m2 rate; J = geometric parts-per-sheet; the WB computes (L/J)×scrap = rate×part_area×scrap.
        # The full-sheet area cancels in L/J, so the cost is exactly area×rate regardless of sheet size.
        _acr_m2 = getattr(config, "ACRYLIC_PRICE_GBP_PER_M2", {}) or {}
        _acr_rate_m2 = None
        try:
            _acr_rate_m2 = _acr_m2.get(float(thickness)) if thickness is not None else None
        except (TypeError, ValueError):
            _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            try:
                _mkeys = [k for k in _acr_m2 if isinstance(k, (int, float))]
                if thickness is not None and _mkeys:
                    _acr_rate_m2 = _acr_m2[min(_mkeys, key=lambda k: abs(k - float(thickness)))]
            except (TypeError, ValueError):
                _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            _acr_rate_m2 = float(_acr_m2.get("default", 8.0))
        # An LLM rate is used ONLY where config holds none -- it never displaces a real one.
        if _llm_rate_m2:
            _acr_rate_m2 = _llm_rate_m2
        _acr_rate_m2 = float(_acr_rate_m2)

        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width, part=part)
        if (_acr_sheet_est or {}).get("rotated"):
            # THE BLANK IS WRITTEN TURNED, so the workbook's own fixed-orientation nest
            # reaches the better yield by its own arithmetic. Howard's 0355255 line 84:
            # 24/sheet as drawn, 26 with length and width exchanged.
            blank_length, blank_width = blank_width, blank_length
            part.setdefault("review_flags", []).append(
                f"NESTED TURNED: {_acr_sheet_est.get('parts_per_sheet')}/sheet with the blank at "
                f"{blank_length:g} x {blank_width:g} beats the drawn orientation — the "
                f"sheet is written with the blank turned. Never done where the material or "
                f"finish has a direction.")
        # full-sheet area from the standard sheet the nester picked (falls back to 3050×2050)
        _acr_sheet_dims = _acr_sheet_est.get("candidate_sheet_size_mm") or [3050.0, 2050.0]
        try:
            _full_sheet_area_m2 = (float(_acr_sheet_dims[0]) * float(_acr_sheet_dims[1])) / 1_000_000.0
        except (TypeError, ValueError, IndexError):
            _full_sheet_area_m2 = (3050.0 * 2050.0) / 1_000_000.0
        # L = real full-sheet price at the UDEF £/m2 (verifiable against a supplier invoice)
        _sheet_price = round(_full_sheet_area_m2 * _acr_rate_m2, 2)
        # ── J: THE WORKBOOK'S RULE, BECAUSE THE WORKBOOK IS WHAT CHARGES THE JOB ──────
        # This used to be full_sheet_area / part_area, with the reasoning that the sheet
        # area cancels in L/J and the cost comes out as exactly area x rate. The algebra is
        # right and the premise is not: wb_populate writes L, the blank L/W and the sheet
        # L/W into the Other Sheet Material row, and the TEMPLATE recomputes J itself from
        # those by its own J51 nesting rule. The engine's J is never read. So the
        # cancellation the comment relied on happens nowhere, and the two artefacts charge
        # different money for the same part.
        #
        # 11650's door, 1202 x 689 on a 3050 x 2050 sheet: the engine said 7.55 parts per
        # sheet and priced GBP 18.69; the sheet nests 4 and charges GBP 35.28. Every report
        # reading the JSON disagreed with the workbook the estimator was holding.
        #
        # WHICH IS COMMERCIALLY RIGHT IS A REAL QUESTION -- area-basis says you pay for the
        # material you use and the offcut is someone else's, nested says you buy whole
        # sheets and get four doors out of one. It is not settled here and it is not settled
        # quietly: the engine now predicts what the workbook will actually charge, and the
        # area figure is kept beside it on the record so the assumption is visible and an
        # estimator can argue with it.
        _part_area_m2 = _acr_area_m2 if _acr_area_m2 and _acr_area_m2 > 0 else (_full_sheet_area_m2 or 1.0)
        # THE NEST THAT PRICES THE LINE IS THE NEST ON THE RECORD. This used to call J51
        # directly, so the money came from one rule and stock_estimate from another, and this
        # branch is entered by ANY material an LLM returns a GBP/m2 rate for -- a steel with no
        # engine price included. select_sheet_size now picks the rule from the material, so a
        # plastic gets J51 and a steel priced this way still gets K38.
        _acr_pps = (_acr_sheet_est or {}).get("parts_per_sheet")
        _area_only_part = _acr_area_m2 * _acr_rate_m2 * (1.0 + _scrap)
        _nest_failed = not _acr_pps
        if _acr_pps:
            # Exactly the template's M = (L/J) x (1+K), so the JSON and the sheet agree.
            _acr_cost_part = (_sheet_price / float(_acr_pps)) * (1.0 + _scrap)
        else:
            # BIGGER THAN THE SHEET, or no usable nest. The template shows "doesn't fit"
            # and charges nothing, which is the one answer that is certainly wrong. Price it
            # by area -- and SAY SO, because this is the one case where the engine and the
            # workbook cannot agree: the sheet will run J51 over the same dimensions, reach
            # the same "doesn't fit", and put an error or a zero in the row. A part that
            # needs a bigger sheet, a different stock size or cutting from two pieces is a
            # buying decision, and nobody can take it from a number that arrived quietly.
            #
            # The comment here used to promise exactly this and the code did not do it.
            _acr_pps = 1
            _acr_cost_part = _area_only_part
        _acr_ext = round(_acr_cost_part * quantity, 2)
        if _llm_rate_m2:
            _acr_note = ("%s has no rate in this engine. Priced at an LLM MARKET INDICATION "
                         "of £%.2f/m2 (£%.2f/sheet, %s) — NOT a supplier quote and not firm; "
                         "confirm with Purchasing."
                         % (material, _acr_rate_m2, _sheet_price,
                            _llm_ind.get("source") or "llm"))
        else:
            _acr_note = ("Acrylic sheet-nested cost (PROVISIONAL) — £%.2f/sheet ÷ %s "
                         "parts/sheet; swap for canonical on estimating confirmation."
                         % (_sheet_price, _acr_pps))
        if _nest_failed:
            _acr_note += (" DOES NOT NEST on a %.0f x %.0f sheet at %.0f x %.0f: priced by "
                          "AREA instead, and the workbook will show this row as not fitting. "
                          "It needs a larger sheet, a different stock size, or cutting from "
                          "two pieces — that is a buying decision, not a rounding."
                          % (_acr_sheet_dims[0], _acr_sheet_dims[1],
                             blank_length or 0, blank_width or 0))
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": round(_acr_area_m2, 4),
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": round(_acr_cost_part, 2),
            "cost_per_part_gbp": round(_acr_cost_part, 2),
            "extended_sheet_material_cost_gbp": _acr_ext,
            "powder_consumable": None,
            "extended_material_cost_gbp": _acr_ext,
            "stock_estimate": _acr_sheet_est,
            # Raw PRE-scrap sheet price (£/sheet) so wb_populate can fill the WB Other Sheet
            # 'Cost per sheet' cell (col L). The WB formula M=(L/J)*(1+K)*D applies scrap (K)
            # and qty-per-sheet (J) itself, so we expose the sheet price, NOT the per-part cost.
            "sheet_price_gbp": round(float(_sheet_price), 2),
            "parts_per_sheet": int(_acr_pps),
            # HOW MUCH OF A SHEET THIS PART'S COST IS, recorded by the calculation that
            # divided it. A checker that worked this out for itself would need a list of the
            # cost methods that divide a sheet, and a list of spellings is exactly what goes
            # stale. Area-priced parts record their real fraction, which is smaller still.
            "sheet_fraction_per_part": (
                round(_part_area_m2 / _full_sheet_area_m2, 6)
                if _nest_failed and _full_sheet_area_m2
                else round(1.0 / float(_acr_pps), 6)),
            # Named from the nest that produced it, not asserted. A line that says J51 while
            # stock_estimate holds a K38 count is the defect this branch already had once.
            "nesting_rule": ((_acr_sheet_est or {}).get("nesting_rule")
                             or _costed_facts.nesting_rule_for(material)),
            # THE OTHER ANSWER, KEPT WHERE IT CAN BE ARGUED WITH. Nested says you buy whole
            # sheets and get four doors out of one; area says you pay for what you use and
            # the offcut is someone else's. The engine charges what the workbook charges,
            # and this is what it would have been on the area basis, so the difference is a
            # number an estimator can see rather than a decision buried in a formula.
            "area_only_cost_per_part_gbp": round(_area_only_part, 2),
            "nesting_uplift_x": (round(_acr_cost_part / _area_only_part, 2)
                                 if _area_only_part else None),
            "cost_method": ("llm_market_sheet_rate" if _llm_rate_m2
                            else "acrylic_area_per_m2_provisional"),
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "reliability_flags": ((["llm_market_rate_not_a_supplier_price"] if _llm_rate_m2 else
                                   [getattr(config, "ACRYLIC_PROVISIONAL_FLAG",
                                            "acrylic_provisional_pending_estimating")])
                                  + (["does_not_nest_on_the_standard_sheet"] if _nest_failed
                                     else [])),
            "note": _acr_note,
            "price_source": _build_price_source_metadata(
                {},
                # "llm_" so is_non_reproducible_source recognises it without a new rule:
                # check_prices_are_firm then reports the job as not firm, automatically.
                fallback_source=("llm_market_sheet_rate" if _llm_rate_m2
                                 else "acrylic_area_per_m2_provisional"),
                applied=True,
                applied_basis=("llm_market_GBP_per_m2" if _llm_rate_m2
                               else "acrylic_area_per_m2_provisional"),
                affects_total=True,
            ),
        }
    external_price = _resolve_material_price(material, thickness, quantity, part=part)
    external_result = external_price.get("result", {})

    # ── ROUND BAR / STUD path (added 2026-07-13) ─────────────────────────────
    # Fires ONLY when document_builder recognised a bar schedule on the part's own page:
    #       ITEM  QTY  DESCRIPTION  LENGTH
    #         1    1    8mm DIA      65
    #
    # This has to be its own branch. The wire path below keys on the WORD "wire" in the
    # description (WIRE MESH / WELDED WIRE / WIRE FORM / ...) — the same spelling test we
    # just removed from document_builder, present here a second time. A solid bar whose
    # drawing says "STUD" can never satisfy it. And gauge_mm there falls back to 3.0 when
    # thickness is absent, which would price an 8mm bar as 3mm wire.
    #
    # Uses the SAME formula and rates as the workbook, so the engine's JSON total and the
    # WB's own Wire block agree:
    #     8mm -> 2534 m/tonne (WB gauge table; also = 1000 / (pi*(d/2000)^2 * 7850))
    #     price/m = £1600 / 2534 = £0.6313
    #     unit    = 0.6313/1000 x 65mm x 1.04 = £0.0427     (Tim's sheet: £0.04)
    if part.get("_bar_recognised"):
        _bar_gauge = _safe_float(part.get("wire_gauge_mm"))
        _bar_len = _safe_float(part.get("wire_length_mm"))
        if _bar_gauge and _bar_len:
            wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
            _wire_per_tonne = float(wb_defaults.get("wire_cost_per_tonne_gbp") or 1600.0)
            _gauge_table = getattr(config, "WIRE_GAUGE_TABLE", {}) or {}
            _m_per_tonne = None
            if _gauge_table:
                _closest = min(_gauge_table.keys(), key=lambda g: abs(float(g) - _bar_gauge))
                # only trust the table if it actually has this gauge (within 0.25mm)
                if abs(float(_closest) - _bar_gauge) <= 0.25:
                    _m_per_tonne = float(_gauge_table[_closest])
            if not _m_per_tonne:
                # derive from the solid round section — matches the WB table exactly
                _area_m2 = 3.14159265 * ((_bar_gauge / 2000.0) ** 2)
                _kg_per_m = _area_m2 * 7850.0
                _m_per_tonne = (1000.0 / _kg_per_m) if _kg_per_m > 0 else None
            if _m_per_tonne and _m_per_tonne > 0:
                _price_per_m = _wire_per_tonne / _m_per_tonne
                _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
                _unit = (_price_per_m / 1000.0) * _bar_len * (1.0 + _scrap)
                _ext = _unit * quantity
                return {
                    "material": material,
                    "thickness_mm": None,          # a DIAMETER is not a thickness
                    "blank_length_mm": _bar_len,
                    "blank_width_mm": None,
                    "blank_area_m2": None,
                    "unit_material_mass_kg": round(_bar_len / 1000.0 / _m_per_tonne * 1000.0, 5),
                    "unit_material_cost_gbp": round(_unit, 4),
                    "cost_per_part_gbp": round(_unit, 4),
                    "extended_material_cost_gbp": round(_ext, 2),
                    "stock_estimate": {
                        "wire_length_mm": _bar_len,
                        "wire_gauge_mm": _bar_gauge,
                        "metres_per_tonne": round(_m_per_tonne, 1),
                        "price_per_metre_gbp": round(_price_per_m, 6),
                    },
                    "cost_method": "workbook_bar_formula",
                    "stock_form": "wire",
                    "wire_gauge_mm": _bar_gauge,
                    "wire_length_mm": _bar_len,
                    "requires_flat_blank": False,
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        external_result, fallback_source="config_wire_cost_per_tonne",
                        applied=True, applied_basis="bar_diameter_x_length_gauge_lookup",
                    ),
                }

    # RECOGNISED AS WIRE/BAR BUT MISSING A TRUSTED DIAMETER OR LENGTH.
    #
    # The bar formula above prices only when it has BOTH a gauge and a TRUSTED length (one from a
    # bar/wire schedule — the only writers of wire_length_mm). Without them the old code fell
    # straight through to the sheet/default path at the bottom of this function and priced the
    # DIAMETER as a plate — 11762-17-03M came out £0.63 and 04M £45.00 off a 5496/6364mm PDF
    # cut OUTLINE (pdf_geometry_inflation_suspected), not a developed centreline. The workbook
    # withheld those, but they were still stamped into material_estimate and shown in Provenance:
    # two answers for one line. A wire has no flat blank; a PDF outline is not a length.
    #
    # KEY THE GUARD ON stock_form == "wire", NOT on _bar_recognised. The latter is a top-level
    # "_"-prefixed flag that does not survive to here (the run that dropped the laser proves
    # stock_form "wire" DOES survive, on manufacturing_interpretation). Sections keep their own
    # linear-stock path below, so exclude them. Result: a recognised wire with no trusted length
    # is an estimator input on WIRE stock, and Provenance reads the SAME cost_method the sheet
    # does — one answer, no invented kilos.
    _mi_wire = part.get("manufacturing_interpretation") or {}
    _me_wire = part.get("material_estimate") or {}
    _is_wire_stock = bool(
        part.get("_bar_recognised")
        or str(_mi_wire.get("stock_form") or "").lower() == "wire"
        or str(_me_wire.get("stock_form") or "").lower() == "wire")
    # SECTION vs WIRE. A hollow a×b×t profile is a TUBE and keeps its own linear-stock path
    # below; a solid round wire/bar is priced HERE. The old conjunct excluded anything
    # _is_section_or_wire_candidate calls "section/wire" -- which fires on the bare word WIRE in
    # the description -- so "U WIRE" / "WIRE STAND" were skipped and fell to the sheet/default
    # rate card at £0.63 / £45. Guard on a REAL tube profile only.
    _ss_wire = part.get("section_stock") or {}
    _is_profile_tube = bool(_ss_wire.get("a") and _ss_wire.get("b") and _ss_wire.get("t"))
    if _is_wire_stock and not _is_profile_tube:
        _wb_w = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
        _wg = (_safe_float(part.get("wire_gauge_mm"))
               or _safe_float(_mi_wire.get("wire_gauge_mm"))
               or _safe_float(_me_wire.get("wire_gauge_mm"))
               or float(getattr(config, "WIRE_DEFAULT_GAUGE_MM", 8.0)))
        # LENGTH: a schedule / CL length only (the sole writer of wire_length_mm). A PDF cut path
        # (5496 / 6364mm on 11762-17) is an OUTLINE, never a developed length, so it is NOT used.
        _wl = _safe_float(part.get("wire_length_mm"))
        _length_assumed = False
        if not _wl or _wl <= 0:
            # Assume a SHORT developed length by FORM until the detail is measured: a compact
            # formed wire (a U, a hook, a clip) is a fraction of a stand / frame. Config-driven,
            # keyed on the description, never a part number.
            _desc_w = str(part.get("description") or part.get("part_number") or "").upper()
            _bands = getattr(config, "WIRE_ASSUMED_DEVELOPED_LENGTH_MM",
                             {"compact": 400.0, "formed": 900.0})
            _compact_kw = getattr(config, "WIRE_COMPACT_KEYWORDS",
                                  ("U WIRE", "U-WIRE", "HOOK", "CLIP", "LOOP", "PIN", "CLASP"))
            _wl = float(_bands.get("compact", 400.0) if any(k in _desc_w for k in _compact_kw)
                        else _bands.get("formed", 900.0))
            _wl = min(_wl, 1500.0)
            _length_assumed = True
        _rate_t = float(_wb_w.get("wire_cost_per_tonne_gbp") or 1600.0)
        _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
        _area_m2 = 3.14159265 * ((_wg / 2000.0) ** 2)
        _kg_per_m = _area_m2 * 7850.0
        _mpt = (1000.0 / _kg_per_m) if _kg_per_m > 0 else None
        _unit = _ext = _mass = None
        if _mpt and _mpt > 0:
            _ppm = _rate_t / _mpt
            _unit = (_ppm / 1000.0) * _wl * (1.0 + _scrap)
            _ext = _unit * quantity
            _mass = _wl / 1000.0 / _mpt * 1000.0
        part.setdefault("review_flags", []).append(
            f"{part.get('part_number')}: wire priced Ø{_wg:g} x {_wl:g}mm at £{_rate_t:.0f}/t"
            + (" — [AI ESTIMATE - INDICATIVE, NOT A QUOTE]; developed length ASSUMED, overwrite "
               "when a schedule / CL callout or Tim gives it (a PDF outline is not a length)."
               if _length_assumed else "."))
        return {
            "material": material,
            "thickness_mm": None,               # a DIAMETER is not a thickness
            "blank_length_mm": _wl,
            "blank_width_mm": None,
            "blank_area_m2": None,
            "unit_material_mass_kg": round(_mass, 5) if _mass is not None else None,
            "unit_material_cost_gbp": round(_unit, 4) if _unit is not None else None,
            "cost_per_part_gbp": round(_unit, 4) if _unit is not None else None,
            "extended_material_cost_gbp": round(_ext, 2) if _ext is not None else None,
            "stock_estimate": {
                "wire_length_mm": _wl, "wire_gauge_mm": _wg,
                "length_assumed": _length_assumed,
                "metres_per_tonne": round(_mpt, 1) if _mpt else None,
            },
            "cost_method": ("wire_tonne_rate_assumed_length" if _length_assumed
                            else "workbook_bar_formula"),
            "stock_form": "wire",
            "wire_gauge_mm": _wg,
            "wire_length_mm": _wl,
            "requires_flat_blank": False,
            "estimator_input_required": _length_assumed,
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "price_source": _build_price_source_metadata(
                external_result, fallback_source="config_wire_cost_per_tonne",
                applied=True,
                applied_basis=("assumed_length_x_tonne_rate" if _length_assumed
                               else "bar_diameter_x_length_gauge_lookup")),
        }

    # Section/tube/wire path: uses linear stock mass estimate when profile+length is available.
    if _is_section_or_wire_candidate(part, material):
        _ss = part.get("section_stock") or {}
        side_a_mm = _safe_float(_ss.get("a"))
        side_b_mm = _safe_float(_ss.get("b"))
        wall_t_mm = _safe_float(_ss.get("t"))
        if not (side_a_mm and side_b_mm and wall_t_mm):
            side_a_mm, side_b_mm, wall_t_mm = _parse_section_profile(str(part.get("description") or ""))
        length_mm = _infer_section_length_mm(part)
        # THE LENGTH IS THE MONEY, SO THE LINE SAYS WHERE THE LENGTH CAME FROM. Section stock
        # is priced per metre. When the length is a reading (7332-01-002: 1,397 mm, transcribed
        # by the LLM as section_stock.length_mm) it is priced like any other reading. When it
        # is the FALLBACK — the largest dimension found anywhere on the part — it is still
        # priced, because a stand's height is usually a fair figure for its leg and a blank
        # helps nobody, but it is priced INDICATIVE with a flag naming the figure, so the
        # estimator confirms the height off the GA rather than discovering it in the total.
        #
        # It is REFUSED only when the fallback figure cannot be a length of stock at all: it is
        # a cut-path total from the same record (7332's 9,106 mm page sum), or longer than any
        # bar of section. That test lives in blank_credibility so the invariant and the
        # pre-flight ask it the same way. An earlier cut of this guard refused EVERY fallback,
        # which would have zeroed a leg on the strength of a diagnosis that was never
        # established — the real run had a transcribed length all along.
        _len_src = str(part.get("_section_length_source") or "")
        _len_reader = str(part.get("_section_length_reader") or "")
        _len_indicative = False
        if length_mm and _len_src == SECTION_LENGTH_FALLBACK:
            import blank_credibility as _bc_len
            _absurd = _bc_len.section_length_is_absurd(part, length_mm)
            if _absurd:
                part.setdefault("review_flags", []).append(
                    f"section length NOT STATED — the only figure on the part is the largest "
                    f"dimension found ({length_mm:,.0f}mm), and that figure {_absurd}. Not "
                    f"priced: enter the cut length (or add it to the SolidWorks cut list).")
                part["_consumable_qty_unknown"] = True
                length_mm = None
            else:
                _len_indicative = True
                part.setdefault("review_flags", []).append(
                    f"section length not stated — taken as largest dimension "
                    f"{length_mm:,.0f}mm (INDICATIVE); confirm the cut length off the GA")
        _len_stamp = {"section_length_source": _len_src or "none",
                      "section_length_reader": _len_reader or "none",
                      "section_length_indicative": _len_indicative}

        # A hollow rolled section is METAL by definition — it cannot be timber/MDF/wood. On these
        # drawings the deterministic reader sometimes tags a tube 'TIMBER' off a nearby spec note,
        # which mis-costs it ~13x (timber density + rate vs steel). With a real a×b×t profile in
        # hand, coerce a non-metal material to mild steel so mass and £/kg are right.
        if side_a_mm and side_b_mm and wall_t_mm and str(material or "").upper().replace("_", " ") in (
                "TIMBER", "WOOD", "MDF", "PLYWOOD", "SOFTWOOD", "OAK", "MDF / OAK VENEER"):
            part.setdefault("review_flags", []).append(
                f"material '{material}' overridden to MILD STEEL — part is a "
                f"{side_a_mm:g}x{side_b_mm:g}x{wall_t_mm:g} hollow section (cannot be timber)")
            material = "MILD STEEL"

        # ── Wire path (workbook rows 28-35) ──────────────────────────────────
        # M = (wire_£_per_tonne / metres_per_tonne / 1000) × length_mm × qty × (1+scrap)
        desc_upper = str(part.get("description") or "").upper()
        is_wire = any(kw in desc_upper for kw in ("WIRE MESH", "WELDED WIRE", "WIRE FORM", "WIREWORK", "WIRE "))
        if is_wire and length_mm:
            wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
            wire_per_tonne = float(wb_defaults.get("wire_cost_per_tonne_gbp") or 1600.0)
            wire_gauge_table = getattr(config, "WIRE_GAUGE_TABLE", {}) or {}
            gauge_mm = _safe_thickness_mm(part) or 3.0
            metres_per_tonne: Optional[float] = None
            if wire_gauge_table:
                closest_gauge = min(wire_gauge_table.keys(), key=lambda g: abs(float(g) - gauge_mm))
                metres_per_tonne = float(wire_gauge_table[closest_gauge])
            if not metres_per_tonne:
                wire_area_m2 = 3.14159 * ((gauge_mm / 2000.0) ** 2)
                kg_per_m = wire_area_m2 * 7850.0
                metres_per_tonne = 1000.0 / kg_per_m if kg_per_m > 0 else 1000.0
            price_per_metre = wire_per_tonne / metres_per_tonne if metres_per_tonne > 0 else 0.0
            scrap_frac = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
            unit_cost = (price_per_metre / 1000.0) * length_mm * (1.0 + scrap_frac)
            extended = unit_cost * quantity
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": length_mm,
                "blank_width_mm": None,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(length_mm / 1000.0 / metres_per_tonne * 1000.0, 4) if metres_per_tonne else None,
                "unit_material_cost_gbp": round(unit_cost, 4),
                "cost_per_part_gbp": round(unit_cost, 4),
                "extended_material_cost_gbp": round(extended, 2),
                "stock_estimate": {"wire_length_mm": length_mm, "metres_per_tonne": metres_per_tonne, "price_per_metre_gbp": round(price_per_metre, 6)} | _len_stamp,
                "cost_method": "workbook_wire_formula",
                "stock_form": "wire",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result, fallback_source="config_wire_cost_per_tonne",
                    applied=True, applied_basis="wire_£_per_tonne_gauge_lookup",
                ),
            }

        if side_a_mm and side_b_mm and wall_t_mm and length_mm:
            # GENUINE catalogue price first: SDI stocks cut/slotted tube as bought-in parts
            # (SLOTTEDTUBE01/02 etc. in UDEF). If the detected profile+length matches a priced
            # catalogue row, use that real per-piece price + supplier instead of a mass*£/kg
            # estimate. Falls through to the mass estimate (flagged) if no catalogue match.
            _cat = _lookup_catalogue_tube_price(side_a_mm, side_b_mm, wall_t_mm, length_mm)
            if _cat and _cat.get("unit_price_gbp"):
                _cat_unit = float(_cat["unit_price_gbp"])
                _cat_ext = round(_cat_unit * quantity, 2)
                part["stock_form"] = "tube"   # so the compiler's fold/punch gate sees a tube
                return {
                    "material": material,
                    "thickness_mm": thickness,
                    "blank_length_mm": blank_length,
                    "blank_width_mm": blank_width,
                    "blank_area_m2": None,
                    "unit_material_mass_kg": None,
                    "unit_material_cost_gbp": round(_cat_unit, 2),
                    "cost_per_part_gbp": round(_cat_unit, 2),
                    "extended_material_cost_gbp": _cat_ext,
                    "stock_estimate": {
                        "section_length_mm": round(length_mm, 2),
                        "catalogue_part_code": _cat.get("part_code"),
                        "catalogue_description": _cat.get("description"),
                        "catalogue_length_mm": _cat.get("catalogue_length_mm"),
                    } | _len_stamp,
                    "stock_form": "tube",
                    "supplier": _cat.get("supplier"),
                    "requires_flat_blank": False,
                    "cost_method": "catalogue_section_price",
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        {}, fallback_source="udef_catalogue_section",
                        applied=True, applied_basis=f"catalogue {_cat.get('part_code')} @ £{_cat_unit:.2f}/{_cat.get('uom') or 'EA'}",
                    ),
                }
            density = MATERIAL_DENSITY_KG_PER_M3.get(material or "", MATERIAL_DENSITY_KG_PER_M3.get("MILD STEEL"))
            # A ROUND TUBE IS NOT A SQUARE ONE.
            #
            # This was the only formula: A = outer - inner, on the sides of a rectangle. Round
            # tube carries its outside diameter in a and b, so a 12.7 x 1.2 CHS computed as
            # 12.7 x 12.7 square gives 55.2mm2 against a true 43.4mm2 — 27% heavy on every
            # metre of every round tube we buy, which is most of the tube we buy.
            inner_a = max(0.0, side_a_mm - (2.0 * wall_t_mm))
            inner_b = max(0.0, side_b_mm - (2.0 * wall_t_mm))
            if str(_ss.get("profile_form") or "").upper() == "CHS":
                area_mm2 = max(0.0, _PI / 4.0 * ((side_a_mm ** 2) - (inner_a ** 2)))
            else:
                area_mm2 = max(0.0, (side_a_mm * side_b_mm) - (inner_a * inner_b))
            kg_per_m = (area_mm2 * (density or 7850.0)) / 1_000_000.0
            unit_length_m = length_mm / 1000.0
            unit_mass_kg = kg_per_m * unit_length_m
            applied_price_per_kg = external_price.get("applied_price_per_kg")
            fallback_price_per_kg = MATERIAL_PRICE_GBP_PER_KG.get(material or "")
            price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg
            # SECTION IS NOT PRICED LIKE SHEET. See config.SECTION_STOCK_PRICE_GBP_PER_KG:
            # the flat-product rate is ~8x too low for small tube. Use the real rate where
            # the estimators have set one; otherwise carry on at the flat rate and SAY SO on
            # the part, so the under-read is visible instead of silent.
            _sec_rate = getattr(config, "SECTION_STOCK_PRICE_GBP_PER_KG", None)
            if isinstance(_sec_rate, dict):
                _sec_rate = _sec_rate.get(str(material or "").upper())
            _sec_rate = _safe_float(_sec_rate)
            if _sec_rate and _sec_rate > 0:
                price_per_kg = _sec_rate
                # INDICATIVE, NOT FIRM. The config section rate is a single global trade hold —
                # right for small thin tube, high for a large section — so it prices the line
                # (no more flat-rate under-read) but is flagged for verify against the actual
                # section size, like the other INDICATIVE holds on this job.
                part.setdefault("review_flags", []).append(
                    f"section material priced at the INDICATIVE trade rate GBP {price_per_kg:.2f}/kg "
                    f"(config.SECTION_STOCK_PRICE_GBP_PER_KG, a global hold) — verify against the "
                    f"section size; a large section is cheaper per kg than this")
            elif price_per_kg is not None:
                part.setdefault("review_flags", []).append(
                    f"section material priced at the FLAT-PRODUCT rate GBP {price_per_kg:.2f}/kg. "
                    f"Small section is not sold on that basis — 12.7x1.2 tube is about "
                    f"GBP 7.29/kg — so this line UNDER-READS, likely several times over. Set "
                    f"config.SECTION_STOCK_PRICE_GBP_PER_KG to the trade rate")
            policy = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
            waste_factor = 1.0 + (float(policy.get("waste_factor_pct", 4.0)) / 100.0)
            unit_cost = (unit_mass_kg * price_per_kg * waste_factor) if price_per_kg is not None else None
            extended = (unit_cost * quantity) if unit_cost is not None else None
            # TAG THE PART ITSELF, not only the material estimate. The route compiler's
            # impossibility gate reads record.stock_form to rule out flat-sheet ops on a tube
            # (fold / line-bend / punch). It reads the part record, so a stock_form that lived
            # only on material_estimate never reached it — which is why 7332-01-002's leg still
            # carried a compiler folding=required against a Tubebend sheet. Write it here.
            part["stock_form"] = "tube"
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(unit_mass_kg, 3),
                "unit_material_cost_gbp": round(unit_cost, 2) if unit_cost is not None else None,
                "cost_per_part_gbp": round(unit_cost, 2) if unit_cost is not None else None,
                "extended_material_cost_gbp": round(extended, 2) if extended is not None else None,
                # THE WASTE IS ALREADY IN THIS NUMBER. unit_cost above is mass x rate x
                # waste_factor (SECTION_STOCK_POLICY, 4% cut loss/trim). The workbook then
                # writes its own 4% scrap into the BOM row and multiplies again, so the leg pair
                # shipped at £12.19 instead of £11.72 — the same allowance charged twice. Say so
                # on the record and the sheet leaves the scrap column alone.
                "waste_included": True,
                "waste_factor_applied": round(waste_factor, 4),
                # NAME THE BOOK THAT PRICED IT. This branch carried no cost_method, so every
                # tab that asks "where did the £ come from" fell to "not named" on the leg
                # while the AI Provenance tab, reading the price_source metadata instead,
                # said "SDI config rate (INDICATIVE)". One line, two answers. The method
                # says which rate was used so one classifier can say the same thing on
                # every surface.
                "cost_method": ("section_stock_config_rate" if (_sec_rate and _sec_rate > 0)
                                else "section_stock_flat_rate"),
                "rate_gbp_per_kg": price_per_kg,
                "stock_estimate": {"section_length_mm": round(length_mm, 2), "kg_per_m": round(kg_per_m, 4)} | _len_stamp,
                # This branch has a full a×b×t hollow-section profile + a real cut length, so it IS a
                # tube — declare it as one (like the catalogue branch above) so the workbook routes it
                # to the tube/BOM block and prices it by length, NOT into the Sheet Steel block as a
                # flat blank (which mis-costs the 30×30 profile as a 30×30 plate).
                "stock_form": "tube",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result,
                    fallback_source="config_default_material_rates",
                    applied=applied_price_per_kg is not None,
                    applied_basis=external_price.get("applied_basis") if applied_price_per_kg is not None else "config_fallback_GBP_per_kg",
                )
                | {"section_profile_mm": {"a": side_a_mm, "b": side_b_mm, "t": wall_t_mm}}
                | _len_stamp,
            }

    # Stated-weight path: when the drawing declares a part weight (e.g. "WEIGHT: 885g"),
    # use it directly instead of computing mass from area x thickness x density.
    # Critical for timber/wood where the extracted thickness is often a tolerance artefact.
    _NON_SHEET_MATERIALS = {"TIMBER", "WOOD", "MDF", "PLYWOOD", "SOFTWOOD"}
    stated_weight_kg = _stated_weight_kg_for_part(part)
    # A LAMINATED BOARD IS BOUGHT BY THE SHEET, NOT MASSED AT THE CORE'S £/kg — however
    # well the model weighed it. 11908-21's trays carry a modelled weight, so this branch
    # returned plain-MDF kilo money before the faced-board promotion below ever ran: the
    # weight was right and the price basis still wrong. The weight stays on the record;
    # only its PRICING is declined, and the sheet-yield branch prices the purchased board.
    if stated_weight_kg is not None and _faced_family:
        stated_weight_kg = None
    # Plausibility gate: a DXF/PDF "stated weight" is trusted only when it agrees with the
    # blank-based mass (area x thickness x density). Bad unit conversions produce weights that
    # are wildly too small (e.g. 0.0007 kg for a ~2.3 kg peg) or too large (the 1450 title-block
    # case); in either direction we ignore the stated weight and fall through to the reliable
    # area formula below. Only gated when there is a blank to check against.
    if stated_weight_kg is not None and stated_weight_kg > 0 and blank_length and blank_width and thickness:
        _pol = getattr(config, "MATERIAL_PRICE_POLICY", {}) or {}
        _max_ratio = float(_pol.get("max_stated_weight_blank_ratio", 3.0))
        _min_ratio = float(_pol.get("min_stated_weight_blank_ratio", 0.5))
        _dens = (MATERIAL_DENSITY_KG_PER_M3.get(material)
                 or MATERIAL_DENSITY_KG_PER_M3.get((material or "").upper(), 7850.0) or 7850.0)
        _area_mass = (blank_length * blank_width / 1_000_000.0) * (thickness / 1000.0) * _dens
        if _area_mass > 0 and not (_min_ratio <= (stated_weight_kg / _area_mass) <= _max_ratio):
            # Stated weight and blank DISAGREE. Which source is reliable decides who wins:
            #  - DXF flat pattern present  -> the blank is measured truth; the odd stated weight
            #    is probably a bad unit conversion -> drop it, use the area formula (original).
            #  - NO DXF (blank is PDF-vision geometry, often garbled e.g. 4.5x4mm) -> the PRINTED
            #    weight is the reliable one -> KEEP it (costs by mass below) and flag the blank.
            # Lever: MATERIAL_PRICE_POLICY.trust_stated_weight_when_no_dxf (default True).
            _dxf_backed = (str(part.get("geometry_source") or "").lower() in (
                "dxf_flat_pattern", "dxf", "dxf_flat") or _has_native_flat(part))
            _trust_wt = bool(_pol.get("trust_stated_weight_when_no_dxf", True))
            if _dxf_backed or not _trust_wt:
                stated_weight_kg = None  # measured blank wins -> use area formula
            else:
                # THE WEIGHT DISPROVES THE BLANK. IT DOES NOT REPLACE IT.
                #
                # 0359342's MBY434 is a 10 g backplate whose blank was INFERRED at
                # 350x250x2mm — 1.37 kg of steel, 137x its own printed weight — and the sheet
                # bought 9.8 m2 of powder and 56 parts of laser time for it. The first fix
                # rescaled that rectangle by sqrt(mass ratio) so laser and powder would follow
                # the weight. THAT WAS WRONG, and a reviewer caught it before it ran: mass and
                # thickness give a NET AREA and nothing else. They do not give an aspect ratio,
                # they do not give a perimeter, and laser time is bought by perimeter. Scaling
                # a fallback envelope produces a rectangle whose proportions were invented by
                # whatever the fallback happened to be — a plausible-looking number in place of
                # an obviously wrong one, which is the worse failure of the two.
                #
                # So the contradiction is RECORDED and the geometry is left unresolved. The
                # material is costed from the printed weight below (that much the evidence does
                # support), and the blank stays visibly the fallback it always was, with the
                # disagreement named on the part so the nest and the cut time are read as the
                # provisional figures they are. The real dimensions are on the part's own
                # detail page; reading them is the fix, and nothing here should pretend to
                # stand in for it.
                _inferred_blank = any("geometry_inferred_provisional" in str(_f)
                                      for _f in (part.get("review_flags") or []))
                _ratio = stated_weight_kg / _area_mass if _area_mass else 0.0
                _factor = (1.0 / _ratio) if 0 < _ratio < 1 else _ratio
                part["blank_contradicted_by_stated_weight"] = {
                    "blank_length_mm": blank_length, "blank_width_mm": blank_width,
                    "blank_implied_kg": round(_area_mass, 4),
                    "stated_weight_kg": stated_weight_kg,
                    "factor": round(_factor, 1),
                    "blank_is_inferred": _inferred_blank,
                }
                part.setdefault("review_flags", []).append(
                    f"blank {blank_length:g}x{blank_width:g}mm implies {_area_mass:.2f}kg "
                    f"against a stated {round(stated_weight_kg * 1000)}g — a factor of "
                    f"{_factor:.0f}. The MATERIAL is costed from the printed weight; the BLANK "
                    f"is left as it stands because a weight gives an area, not a shape or a cut "
                    f"length. "
                    + ("That blank is an inferred fallback envelope, so the nest, the laser "
                       "time and the coated area on this part are provisional and probably "
                       "wrong: read the real size off the part's detail page."
                       if _inferred_blank else
                       "A part with cut-outs weighs less than its rectangle and the stock is "
                       "still bought at full size, so confirm which the weight describes."))
    # ── THE TITLE BLOCK AND THE BLANK DISAGREE, AND NOBODY IS TOLD ──────────────────
    #
    # James Gray, 17 Sep 2026, on 401912-02: "If the engine prints a different steel mass,
    # flag it against 1.7 kg — do not silently overwrite the title block."
    #
    # The gate above fires only on a WILD disagreement — outside half to three times — and
    # says nothing at all inside that band. 401912-02 sits squarely inside it: a 460 x 356.6
    # blank of 2 mm CR4 is 2.57 kg and the title block says 1.7 kg, a ratio of 0.66. No
    # flag, no choice recorded, and the material silently costed from the lighter figure.
    #
    # Both numbers are usually right and they are NOT the same quantity. A stated weight is
    # the FINISHED part; the blank is what is BOUGHT. On a part with a big window the
    # difference is the cut-out, which is paid for and thrown away — so costing the net
    # weight under-buys the steel by exactly the size of the hole. On a part with no
    # cut-outs they should agree, and a gap means something is wrong with one of them.
    #
    # Nothing is overwritten here and nothing changes price: the engine says which figure
    # it used, what the other one was, and what the difference means. An estimator can then
    # settle in five seconds a question that is invisible today.
    if (stated_weight_kg is not None and stated_weight_kg > 0
            and blank_length and blank_width and thickness):
        _chk_dens = (MATERIAL_DENSITY_KG_PER_M3.get(material)
                     or MATERIAL_DENSITY_KG_PER_M3.get((material or "").upper()))
        _chk_blank = ((blank_length * blank_width / 1_000_000.0) * (thickness / 1000.0)
                      * float(_chk_dens)) if _chk_dens else 0.0
        _tol = float((getattr(config, "MATERIAL_PRICE_POLICY", {}) or {}).get(
            "stated_weight_blank_report_tolerance", 0.10))
        if _chk_blank > 0 and abs(stated_weight_kg - _chk_blank) > _chk_blank * _tol:
            # ── A MEASURED BLANK BUYS THE STEEL; THE WEIGHT CHECKS IT ────────────────
            #
            # James Gray, 401912-02: "Steel cost from nested blank area, with 1.7 kg only a
            # sanity check." That is the transaction. A laser part is nested on a sheet and
            # you pay for its share of that sheet, cut-out and all — the window is scrap
            # you bought. Costing the finished weight is buying back the hole.
            #
            # Scoped to a MEASURED flat pattern, and deliberately. Where the blank came
            # from a DXF it is the stronger fact and the weight is the check. Where there
            # is no DXF the blank is PDF vision, often garbled, and the printed weight is
            # the stronger fact — that is the existing behaviour above and it stays.
            _dxf_blank = (str(part.get("geometry_source") or "").lower() in (
                "dxf_flat_pattern", "dxf", "dxf_flat") or _has_native_flat(part))
            _from = "blank" if _dxf_blank else "stated_weight"
            part["stated_weight_vs_blank"] = {
                "stated_weight_kg": round(float(stated_weight_kg), 3),
                "blank_implied_kg": round(_chk_blank, 3),
                "blank_length_mm": blank_length, "blank_width_mm": blank_width,
                "costed_from": _from,
            }
            part.setdefault("review_flags", []).append(
                f"MASS: the drawing states {float(stated_weight_kg):g} kg and the "
                f"{blank_length:g} x {blank_width:g} x {thickness:g} mm blank implies "
                f"{_chk_blank:.2f} kg. The material on this line is costed from "
                + (f"the MEASURED BLANK ({_chk_blank:.2f} kg), because a nested part is "
                   f"bought as its share of a sheet and the cut-out is scrap that was paid "
                   f"for. The stated weight is the finished part and is kept as the check "
                   f"it is — the two differ by "
                   f"{abs(_chk_blank - float(stated_weight_kg)):.2f} kg."
                   if _dxf_blank else
                   f"the STATED {float(stated_weight_kg):g} kg, because there is no "
                   f"measured flat pattern and a blank read off a drawing image is the "
                   f"weaker of the two.")
                + (" A part with cut-outs weighs less than its blank, which is the ordinary "
                   "reason for a gap this way round."
                   if stated_weight_kg < _chk_blank else
                   " The stated weight is HEAVIER than the blank, which a flat part cannot "
                   "be — confirm the gauge and the blank size.")
                + " The title block is not overwritten.")
            if _dxf_blank:
                # Costing falls through to the blank-area path below. The figure itself is
                # untouched on the record — it is a fact about the part, not about the price.
                stated_weight_kg = None

    if stated_weight_kg is not None and stated_weight_kg > 0:
        applied_price_per_kg = external_price.get("applied_price_per_kg")
        fallback_price_per_kg = _price_per_kg_for_material(part, material)
        price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg
        if price_per_kg is not None:
            waste_factor = 1.0 + (NESTING_RULES["waste_factor_pct"] / 100.0)
            unit_cost = stated_weight_kg * price_per_kg * waste_factor
            extended = unit_cost * quantity
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(stated_weight_kg, 3),
                "unit_material_cost_gbp": round(unit_cost, 2),
                "cost_per_part_gbp": round(unit_cost, 2),
                "extended_material_cost_gbp": round(extended, 2),
                "stock_estimate": None,
                "stock_form": "stated_weight",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result,
                    fallback_source="config_default_material_rates",
                    applied=applied_price_per_kg is not None,
                    applied_basis=(external_price.get("applied_basis") if applied_price_per_kg is not None
                                   else "config_fallback_GBP_per_kg"),
                )
                | {
                    "stated_weight_kg": stated_weight_kg,
                    "weight_source": _weight_source_label(part),
                },
            }

    if not material or thickness is None or blank_length is None or blank_width is None:
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": None,
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": None,
            "extended_material_cost_gbp": None,
            "stock_estimate": select_sheet_size(material, blank_length, blank_width),
            "price_source": _build_price_source_metadata(
                external_result,
                fallback_source="config_default_material_rates",
                applied=False,
                applied_basis=None,
            ),
        }

    # ── FACED BOARD: PRICED BY THE SHEET, THE WAY IT IS BOUGHT ──────────────────────
    # A board is bought as a sheet and cut down; the £/kg path prices it as if it were sold
    # by mass, which is not the transaction. The manual estimates all do sheet-price ÷
    # parts-per-sheet × scrap, and the corpus rows carry cost_per_sheet_gbp for exactly that
    # reason. This runs BEFORE the mass path so a board with a known sheet rate never falls
    # through to per-kg — and a board WITHOUT one still falls through and stays unpriced.
    #
    # A LAMINATED CORE IS BOUGHT PRE-FACED. The drawing says "MDF" and "LAMINATED"
    # separately; the purchase order says one thing: faced board. Promoted only on the
    # drawing's own evidence (see _faced_board_promotion), and once promoted the part may
    # NOT fall back to the bare core's £/kg — plain-MDF money on a laminated panel is the
    # 4x under-charge 11908-21 shipped, wearing a real-looking price.
    # ASKED ONCE, ABOVE. The promotion now runs in front of the live-catalogue branch (the
    # only place it could be overtaken), and `_faced_family` / `_cost_family` carry its
    # answer down here. Asking again would double the evidence flag on every faced part.
    _board_rate, _board_note = _board_sheet_rate(_cost_family, thickness)
    if _faced_family:
        if not _board_rate:
            # ── RUNG 4 FOR A BOARD, BECAUSE IT IS THE LAST RUNG AND NOT A BOUGHT-IN'S ──
            #
            # James Gray: "it's lame not to price the MDF and Tony is sarcastic and will
            # laugh about it." He is right. SDI Live was asked (above, for the faced
            # family) and had nothing; config's own points were withdrawn in D-103 because
            # they came off an estimator's sheet. That left a real material with a real
            # measured area reading as unpriced — not because the rules forbid a price,
            # but because the researched rung had only ever been wired into the bought-in
            # chain. It is not a property of being a bought-in; it is the bottom of the
            # ladder, and every line is entitled to it.
            #
            # What comes back is an evidenced figure or nothing: a source, a date, what it
            # is per, the quantity it was found at, and the arithmetic from that figure to
            # this part. Labelled as rung 4 on every document, exactly as a researched
            # bought-in is. Where the research cannot produce all of that, the line stays
            # unpriced and visible — which is the branch below, unchanged.
            _res = _researched_board_rate_m2(_faced_family, thickness, part)
            if _res:
                _res_unit = round(float(_res["price_gbp"]) * (1.0 + float(
                    getattr(config, "SCRAP_PERCENTAGE", 0.04))), 2)
                _res_ev = _res.get("evidence") or {}
                part.setdefault("review_flags", []).append(
                    f"{_faced_family} at {thickness:g}mm: no SDI Live or catalogue rate, so "
                    f"this is a RESEARCHED indicative price — "
                    f"{(_res.get('calculation') or {}).get('working')}, plus scrap, from "
                    f"{_res_ev.get('source')} as at {_res_ev.get('as_of')} "
                    f"({_res_ev.get('quantity_basis')}). {_res.get('status')}: confirm "
                    f"against a current supplier price before it goes out firm.")
                return {
                    "material": material, "thickness_mm": thickness,
                    "blank_length_mm": blank_length, "blank_width_mm": blank_width,
                    "blank_area_m2": round((blank_length * blank_width) / 1_000_000.0, 4),
                    "unit_material_mass_kg": None,
                    "unit_material_cost_gbp": _res_unit,
                    "cost_per_part_gbp": _res_unit,
                    "extended_sheet_material_cost_gbp": round(_res_unit * quantity, 2),
                    "extended_material_cost_gbp": round(_res_unit * quantity, 2),
                    "powder_consumable": None,
                    "stock_estimate": select_sheet_size(_faced_family, blank_length,
                                                        blank_width),
                    "cost_method": "board_rate_researched",
                    "costing_material_family": _faced_family,
                    "scrap_pct": round(float(getattr(config, "SCRAP_PERCENTAGE", 0.04)), 4),
                    "reliability_flags": ["indicative_price", "llm_indicative"],
                    "indicative_price": _res,
                    "note": (f"{_faced_family} researched indicative rate — "
                             f"{_res_ev.get('source')}, {_res_ev.get('as_of')}"),
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        {}, fallback_source="llm_indicative_researched",
                        applied=True, applied_basis="GBP_per_m2_researched"),
                }
            part.setdefault("review_flags", []).append(
                f"FACED BOARD UNPRICED: no purchased sheet price for {_faced_family} at "
                f"{thickness:g}mm, and the researched rung could not produce an evidenced "
                f"figure either. NOT costed as plain {material} — that would charge "
                f"raw-core money for a laminated panel. Give the sheet price and size "
                f"bought and every job on this board prices itself.")
            return {
                "material": material, "thickness_mm": thickness,
                "blank_length_mm": blank_length, "blank_width_mm": blank_width,
                "blank_area_m2": round((blank_length * blank_width) / 1_000_000.0, 4),
                "unit_material_mass_kg": None,
                "unit_material_cost_gbp": None, "cost_per_part_gbp": None,
                "extended_material_cost_gbp": None,
                "stock_estimate": select_sheet_size(_faced_family, blank_length,
                                                    blank_width),
                "cost_method": "faced_board_unpriced",
                "costing_material_family": _faced_family,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    {}, fallback_source="sdi_history_board_sheet_price",
                    applied=False, applied_basis=None),
            }
    if _board_rate and blank_length and blank_width:
        _b_sheet = select_sheet_size(_cost_family, blank_length, blank_width)
        # THE YIELD IS COMPUTED ON THE SHEET THE MONEY BOUGHT. Where the price point
        # states its sheet (£172 buys a 3080x1220), the nester's preferred stock size is
        # overridden: dividing one sheet's price by a bigger sheet's yield understates
        # every part on the job.
        _b_paid_sheet = _board_priced_sheet_mm(_cost_family, thickness)
        if _b_paid_sheet:
            _paid_nest = _costed_facts.nest_on_sheet(
                _cost_family, blank_length, blank_width,
                _b_paid_sheet[0], _b_paid_sheet[1])
            if _paid_nest and _paid_nest.get("parts_per_sheet"):
                _b_sheet = {
                    "candidate_sheet_size_mm": [_b_paid_sheet[0], _b_paid_sheet[1]],
                    "utilisation_pct": round(
                        _paid_nest["parts_per_sheet"] * blank_length * blank_width
                        / (_b_paid_sheet[0] * _b_paid_sheet[1]) * 100.0, 2),
                    **_paid_nest,
                }
        _b_pps = max(1, int(_b_sheet.get("parts_per_sheet") or 1))
        _b_scrap = 1.0 + float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
        _b_unit = (_board_rate / _b_pps) * _b_scrap
        part.setdefault("review_flags", []).append(
            f"{_cost_family} sheet price {_board_note} £{_board_rate:.2f}/sheet ÷ {_b_pps} "
            f"parts per {_b_sheet.get('candidate_sheet_size_mm')} sheet × {_b_scrap:.2f} "
            f"scrap = £{_b_unit:.2f}/part. INDICATIVE, from SDI's own purchase history — "
            f"confirm the current rate before quoting.")
        return {
            "material": material, "thickness_mm": thickness,
            "blank_length_mm": blank_length, "blank_width_mm": blank_width,
            "blank_area_m2": round((blank_length * blank_width) / 1_000_000.0, 4),
            "unit_material_mass_kg": None,
            # THE WORKBOOK'S OTHER SHEET BLOCK NEEDS THE SHEET PRICE, NOT ONLY THE PART
            # PRICE. Its template formula is Cost Per Part = (cost_per_sheet / parts_per_sheet)
            # x (1+scrap) x qty, so a blank cost-per-sheet computes to zero however well the
            # part cost was derived. wb_populate reads `sheet_price_gbp`, or reconstructs it
            # from a TOP-LEVEL `parts_per_sheet` — and this record published neither, so the
            # engine held the panel at GBP 37.95 while the sheet showed GBP 0 and the
            # material total stayed at GBP 1.75. Built, and not wired.
            "sheet_price_gbp": round(_board_rate, 2),
            "parts_per_sheet": _b_pps,
            "scrap_pct": round(_b_scrap - 1.0, 4),
            "unit_material_cost_gbp": round(_b_unit, 2),
            "cost_per_part_gbp": round(_b_unit, 2),
            "extended_sheet_material_cost_gbp": round(_b_unit * quantity, 2),
            "powder_consumable": None,
            "extended_material_cost_gbp": round(_b_unit * quantity, 2),
            "stock_estimate": _b_sheet,
            "cost_method": "board_sheet_yield",
            "costing_material_family": _cost_family,
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "reliability_flags": ["board_sheet_priced", "indicative_price"],
            "note": f"Faced board, sheet-nested: {_board_note}",
            "price_source": _build_price_source_metadata(
                {}, fallback_source="sdi_history_board_sheet_price",
                applied=True, applied_basis="GBP_per_sheet_nested"),
        }

    area_m2 = (blank_length * blank_width) / 1_000_000.0
    thickness_m = thickness / 1000.0
    # AN UNKNOWN MATERIAL IS NOT STEEL. This defaulted every material it did not recognise
    # to 7850 kg/m3 — mild steel — which is a reasonable guess for an unlisted METAL and a
    # 10x error on board. Faced board is deliberately not in the density table (see
    # json_normaliser: giving it one without a rate would cost a chipboard panel at steel's
    # per-kg rate), and today it survives only because it has no £/kg entry either. That is
    # one config edit away from a 1434 x 748 panel being massed as a steel plate.
    #
    # A board with no density recorded now returns None, which lands in the `no_price`
    # branch below and reaches the sheet as a visible unpriced line. Metals keep the steel
    # default: an unlisted alloy really is about that dense, and the guess is defensible.
    density = (MATERIAL_DENSITY_KG_PER_M3.get(material)
               or MATERIAL_DENSITY_KG_PER_M3.get((material or "").upper()))
    if density is None:
        _mat_u = str(material or "").upper().replace("_", " ")
        _is_board_mat = any(
            _t in _mat_u
            for _t in (tuple(getattr(config, "FACED_BOARD_TOKENS", ()))
                       + tuple(getattr(config, "SHEET_BOARD_TOKENS", ()))
                       + tuple(getattr(config, "SOLID_TIMBER_TOKENS", ()))))
        if _is_board_mat:
            part.setdefault("review_flags", []).append(
                f"{material}: no density recorded, so its material cannot be massed and is "
                f"NOT costed. Board is deliberately not defaulted to steel's 7850 kg/m3 — "
                f"that would be a 10x error. Set a sheet rate or a density for this board.")
        else:
            density = 7850.0
    fallback_price_per_kg = _price_per_kg_for_material(part, material)
    applied_price_per_kg = external_price.get("applied_price_per_kg")
    price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg

    # ── RUNG 4 FOR A RECOGNISED SHEET MATERIAL THAT HAS NO RATE ─────────────────────
    #
    # config.MATERIAL_PRICE_GBP_PER_KG holds a comment naming this exact case: "PETG, HIPS,
    # ABS, PVC, FOAMEX, PP and PS have a sheet size and a density above but DELIBERATELY NO
    # RATE HERE." The refusal is right — a price is a commercial fact SDI owns, and inventing
    # one is worse than the gap. But `_researched_board_rate_m2` says the other half out
    # loud: "Rung 4 is not a property of being a bought-in; it is the last rung, and every
    # line is entitled to it" — and it was wired for FACED BOARD only. So a board reached the
    # bottom rung and a plastic fell off the ladder, on packs where the plastic IS the job.
    #
    # 11650's PETG side panels are the standing example, named in that config comment and in
    # estimator_inputs' NO_VOCABULARY branch: a part with a measured blank, a known density
    # and a known sheet size, reported as UNDER-CHARGED and costing £0.
    #
    # THE RATE COMES BACK PER SQUARE METRE AND IS CONVERTED HERE, with the arithmetic shown,
    # because this path costs by mass: £/kg = (£/m² ÷ gauge in metres) ÷ density. Nothing is
    # invented — where the research cannot produce a source, a date and a quantity basis it
    # returns nothing and the line stays unpriced and visible, exactly as it is today.
    if price_per_kg is None and material and density and _safe_float(thickness):
        _res_sheet = _researched_board_rate_m2(material, thickness, part, noun="sheet")
        _res_m2 = _safe_float((_res_sheet or {}).get("unit_price_gbp"))
        if _res_m2 and _res_m2 > 0:
            _thk_m = float(_safe_float(thickness)) / 1000.0
            _kg_per_m2 = _thk_m * float(density)
            if _kg_per_m2 > 0:
                price_per_kg = round(_res_m2 / _kg_per_m2, 4)
                _ev = (_res_sheet.get("evidence") or {})
                part.setdefault("review_flags", []).append(
                    f"{material} at {_safe_float(thickness):g}mm: no SDI Live, catalogue or "
                    f"config rate, so this is a RESEARCHED indicative price — "
                    f"GBP {_res_m2:,.2f}/m2 over {_kg_per_m2:.3f} kg/m2 = "
                    f"GBP {price_per_kg:,.2f}/kg, from {_ev.get('source')} as at "
                    f"{_ev.get('as_of')} ({_ev.get('quantity_basis')}). "
                    f"{_res_sheet.get('status')}: confirm against a current supplier price "
                    f"before it goes out firm. A rate in "
                    f"config.MATERIAL_PRICE_GBP_PER_KG ends the question for every job.")
                part["_researched_sheet_rate"] = _res_sheet

    sheet_estimate = select_sheet_size(material, blank_length, blank_width)

    # Sheet steel cost — workbook rows 37-48 formula:
    # cost_per_part = (sheet_steel_£_per_tonne / 1000 × kg_per_sheet) / parts_per_sheet × (1+scrap)
    wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    is_steel = (material or "").upper() in {
        "MILD STEEL", "MILD_STEEL", "ZINTEC", "GALVANISED STEEL",
        "GALVANIZED STEEL", "STAINLESS STEEL", "STAINLESS_STEEL",
        "MILD_STEEL_SPCC", "STAINLESS_STEEL_304", "STAINLESS_STEEL_316",
    }
    sheet_steel_per_tonne, _steel_rate_from = config.workbook_input_value(
        "sheet_steel_cost_per_tonne_gbp")
    sheet_steel_per_tonne = float(sheet_steel_per_tonne or 0.0)
    cfg_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    sane_default_tonne = float(cfg_defaults.get("sheet_steel_cost_per_tonne_gbp") or 800.0)
    if sheet_steel_per_tonne > 2500.0 or sheet_steel_per_tonne < 200.0:
        sheet_steel_per_tonne = sane_default_tonne
        _steel_rate_from = (f"config.WORKBOOK_INPUT_DEFAULTS — the sheet's own figure was "
                            f"outside £200–£2,500/tonne and was not used")
    scrap_frac = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
    parts_per_sheet = sheet_estimate.get("parts_per_sheet")
    if not parts_per_sheet or int(parts_per_sheet) < 1:
        parts_per_sheet = 1

    # ── ONE RATE FOR STEEL SHEET, AND IT IS THE SHEET'S ─────────────────────────────
    #
    # "No parallel steel-price resolver for this route" — James Gray, 18 Sep 2026. A steel
    # part with a blank is bought as its share of a sheet at the rate the estimator holds in
    # the workbook, and the per-kilo path below must not offer a second answer to a question
    # the sheet has already answered. `density is None` still refuses (no mass, no cost) but
    # a MISSING per-kg rate is no longer a reason to abandon the sheet formula: the formula
    # does not use one.
    _steel_sheet_route = bool(is_steel and sheet_steel_per_tonne > 0 and parts_per_sheet > 0
                              and density is not None and area_m2 and thickness_m)
    if not _steel_sheet_route and (density is None or price_per_kg is None):
        mass_kg = None
        material_cost = None
        cost_method = "no_price"
    elif _steel_sheet_route:
        # Exact workbook formula: cost/part = (£/tonne × kg/sheet) / (1000 × parts/sheet)
        sheet_dims = sheet_estimate.get("candidate_sheet_size_mm") or [2500.0, 1250.0]
        sheet_area_m2 = (float(sheet_dims[0]) * float(sheet_dims[1])) / 1_000_000.0
        kg_per_sheet = sheet_area_m2 * (thickness or 1.0) / 1000.0 * (density or 7850.0)
        cost_per_sheet = (sheet_steel_per_tonne / 1000.0) * kg_per_sheet
        cost_per_part = cost_per_sheet / parts_per_sheet
        mass_kg = area_m2 * thickness_m * density
        material_cost = cost_per_part * (1.0 + scrap_frac)
        cost_method = "workbook_sheet_steel_formula"
        # THE RATE AND WHERE IT CAME FROM, ON THE RECORD. The report and the workbook then
        # state the same figure for the same reason, instead of publishing two numbers and
        # leaving the reader to guess which is the money.
        part["steel_rate_used"] = {
            "gbp_per_tonne": round(float(sheet_steel_per_tonne), 2),
            "source": _steel_rate_from,
            "parts_per_sheet": int(parts_per_sheet),
            "sheet_mm": [sheet_dims[0], sheet_dims[1]],
        }
        # SAID ONLY WHERE THERE WAS A REAL SECOND ANSWER. The config £/kg fallback exists
        # for every steel on the books and was never going to price this line — flagging it
        # would put a sentence on every steel part in the shop, which is how a warning stops
        # being read. An APPLIED per-kilo rate is different: the price service found one,
        # for this part, and it is being refused.
        if applied_price_per_kg is not None and abs(
                float(applied_price_per_kg) * 1000.0 - float(sheet_steel_per_tonne)) > 1.0:
            part.setdefault("review_flags", []).append(
                f"STEEL RATE: costed at £{sheet_steel_per_tonne:,.0f}/tonne from "
                f"{_steel_rate_from}. A live per-kilo rate of "
                f"£{float(applied_price_per_kg):.2f}/kg "
                f"(£{float(applied_price_per_kg) * 1000.0:,.0f}/tonne) was also available "
                f"and was NOT used — the sheet's own cell is the controlling rate and an "
                f"estimator changes it there.")
    else:
        mass_kg = area_m2 * thickness_m * density
        cap_kg = float((getattr(config, "MATERIAL_PRICE_POLICY", {}) or {}).get("max_sane_gbp_per_kg", 15.0))
        eff_price = price_per_kg
        if eff_price is not None and eff_price > cap_kg and is_steel:
            eff_price = float(
                MATERIAL_PRICE_GBP_PER_KG.get((material or "").upper())
                or MATERIAL_PRICE_GBP_PER_KG.get("MILD STEEL", 0.8)
            )
        material_cost = mass_kg * eff_price * (1.0 + scrap_frac) if eff_price is not None else None
        cost_method = "mass_times_price_per_kg"

    # EVERY OTHER APPLIED FINISH, BESIDE POWDER RATHER THAN INSTEAD OF IT. Powder keeps its own
    # workbook formula (by mass, both faces, oven); vinyl, laminate, print, foil, paint and UV
    # are charged by coated area and had no home at all — so a drawing that stated one was
    # costed at nothing and nothing said so. Written onto the part whether or not a rate exists:
    # where none does, the line names the finish, the area and who has to price it.
    _applied_finish = applied_finish.applied_finish_estimate(
        part, blank_length, blank_width, quantity)
    if _applied_finish:
        part["applied_finish_estimate"] = _applied_finish

    powder_block = _powder_consumable_estimate(part, blank_length, blank_width, quantity)
    # acrylic_powder_suppressed_v1 (2026-07-15): powder coat is a STEEL finish. Acrylic /
    # perspex / PMMA / polycarbonate are diamond polished, never powder coated. Suppress the
    # powder CONSUMABLE (BOM material line) at source for these materials, so no phantom POWDER
    # row reaches the workbook, rollups or totals. (The powder OPERATION is already gated out in
    # the acrylic routing block; this handles the material line.)
    _mat_pw = str(material or part.get("normalized_material") or "").upper().replace("_", " ")
    if _mat_pw in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"} \
            or part.get("acrylic_no_powder"):
        powder_block = None
    powder_ext = float((powder_block or {}).get("extended_powder_material_cost_gbp") or 0.0)
    sheet_ext = round((material_cost or 0.0) * quantity, 2) if material_cost is not None else None
    if sheet_ext is not None:
        combined_ext = round(sheet_ext + powder_ext, 2)
    elif powder_ext:
        combined_ext = round(powder_ext, 2)
    else:
        combined_ext = None

    return {
        "material": material,
        "thickness_mm": thickness,
        "blank_length_mm": blank_length,
        "blank_width_mm": blank_width,
        "blank_area_m2": round(area_m2, 4),
        "unit_material_mass_kg": round(mass_kg, 3) if mass_kg is not None else None,
        "unit_material_cost_gbp": round(material_cost, 2) if material_cost is not None else None,
        "cost_per_part_gbp": round(material_cost, 2) if material_cost is not None else None,
        "extended_sheet_material_cost_gbp": sheet_ext,
        "powder_consumable": powder_block if powder_block else None,
        "extended_material_cost_gbp": combined_ext,
        "stock_estimate": sheet_estimate,
        # SET ONLY WHERE A SHEET WAS ACTUALLY DIVIDED. The mass path charges kg at a rate and
        # never touches parts_per_sheet, so claiming a sheet fraction for it would be an
        # invented fact -- and the whole reason this is stamped by the calculation rather than
        # inferred by a reader is that a reader cannot tell those two apart from the record.
        **({"sheet_fraction_per_part": round(1.0 / float(parts_per_sheet), 6)}
           if cost_method == "workbook_sheet_steel_formula" and parts_per_sheet else {}),
        "cost_method": cost_method,
        "stock_form": part.get("manufacturing_interpretation", {}).get("stock_form"),
        "requires_flat_blank": part.get("manufacturing_interpretation", {}).get("requires_flat_blank"),
        "part_confidence_overall": _part_confidence_overall(part),
        "part_geometry_reliability": _part_geometry_reliability(part),
        "price_source": _build_price_source_metadata(
            external_result,
            # A RESEARCHED RATE SAYS SO HERE OR IT LOOKS LIKE A CONFIG RATE. The name
            # begins "llm_" so `is_non_reproducible_source` recognises it with no new rule
            # and check_prices_are_firm reports the job as not firm by itself — the same
            # treatment the acrylic market rate already gets on the area path.
            fallback_source=(
                "workbook_sheet_steel_formula" if cost_method == "workbook_sheet_steel_formula"
                else "llm_indicative_researched" if part.get("_researched_sheet_rate")
                else "config_default_material_rates"
            ),
            applied=(
                True if cost_method == "workbook_sheet_steel_formula"
                else True if part.get("_researched_sheet_rate")
                else applied_price_per_kg is not None
            ),
            applied_basis=(
                "workbook_sheet_steel_formula" if cost_method == "workbook_sheet_steel_formula"
                else "GBP_per_m2_researched_converted_to_GBP_per_kg"
                if part.get("_researched_sheet_rate")
                else (external_price.get("applied_basis") if applied_price_per_kg is not None
                      else "config_fallback_GBP_per_kg")
            ),
            # `applied` HERE MEANS "AN EXTERNAL LOOKUP SUPPLIED THE RATE", NOT "THIS LINE HAS
            # A PRICE". A part priced from MATERIAL_PRICE_GBP_PER_KG has applied=False and a
            # real cost, and stamp_affects_total falls back to `applied` when nothing else is
            # recorded -- so every config-priced material line reported "reached the total:
            # False" while its money sat in the total. It sent this investigation down the
            # wrong path twice: the diagnostic correctly printed what the stamp said, and what
            # the stamp said was not true.
            #
            # Two questions, two fields. Whether a figure exists for this line is
            # material_cost is not None; where the RATE came from stays `applied`.
            affects_total=material_cost is not None,
        ),
    }


def _peg_family_punch_cycle(part: Dict[str, Any]):
    """Machine-measured TruPunch cycle time for known peg-family panels.

    These parts are punched (cluster + tooth + perimeter tooling), but the DXF/PDF
    under-reads their perforation so the hole-count punch model collapses to ~0.
    Returns (minutes, basis_note) keyed on description/PN + panel size, or None.
    1m values are measured from TruPunch setup plans; 500mm is scaled x0.65.
    """
    table = getattr(config, "PUNCH_CYCLE_TIME_MIN", {}) or {}
    blob = (str(part.get("description") or "") + " " + str(part.get("part_number") or "")).upper()
    if "HALF PEG" in blob or "HALF HEIGHT PEG" in blob:
        family = "HALF_PEG"
    elif "PEG PANEL" in blob or "PEG METAL" in blob or "PEG" in blob:
        family = "PEG_PANEL"
    elif "BASE PLATE" in blob:
        family = "BASE_PLATE"
    else:
        return None
    sizes = table.get(family) or {}
    if "1000MM" in blob or "1000 MM" in blob or " 1M " in (" " + blob + " "):
        size = "1000mm"
    elif "500MM" in blob or "500 MM" in blob:
        size = "500mm"
    else:
        return None  # size not stated -- do not guess
    minutes = sizes.get(size)
    if not minutes:
        return None
    basis = (
        f"Punch {minutes} min/part: TruPunch 1000 machine cycle, {family} {size} "
        f"({'measured 1m plan' if size == '1000mm' else 'scaled x0.65 from 1m plan'}); "
        f"DXF/PDF under-reads perforation -- verify with CNC programmer."
    )
    return (float(minutes), basis)


def _is_punch_part(part: Dict[str, Any], holes: int, desc_blob: str) -> bool:
    """Decide whether a sheet-metal part is a PUNCH job rather than laser.

    Two corpus-validated signals (2023 manual estimates, 3,055 records):
      - geometric: a dense field of holes (uneconomic to laser-pierce one by one);
      - descriptive: peg / slotted / perforated / mesh parts (peg = 5.9x punch-lift).
    Caller gates this to sheet metals only.
    """
    cfg = getattr(config, "PUNCH_RECOGNITION", {}) or {}
    if not cfg.get("enabled", True):
        return False
    holes = int(holes or 0)
    if holes >= int(cfg.get("min_holes_for_punch", 24)):
        return True
    blob = (desc_blob or "").upper()
    kws = cfg.get("punch_keywords", []) or []
    if any(k in blob for k in kws) and holes >= int(cfg.get("min_holes_with_keyword", 8)):
        return True
    return False


# Special / bought-in FINISHING items — mirror mosaic tiles, ceramic/glass tiles,
# graphic panels, vinyl/decal graphics. These are NOT SDI-fabricated: they carry no
# saw/glue/CNC/laser/weld fab labour. Dual gate so it stays general:
#   - part number ends in the M&S '-X' special/finishing suffix (e.g. 12301-08-04X), OR
#   - description names a tile/mosaic/graphic/vinyl item
# Keyed on BOTH so a future '-X' that is genuinely a different item still needs the
# description to match, and a tile item without the suffix is still caught.
_SPECIAL_ITEM_DESC_RE = re.compile(
    r"\b(TILE|TILES|MOSAIC|GRAPHIC\s+PANEL|GRAPHIC|VINYL|DECAL)\b",
    re.IGNORECASE,
)


def _is_special_bought_in_item(part: Dict[str, Any]) -> bool:
    pn = str(part.get("part_number") or "").strip().upper()
    desc = " ".join([
        str(part.get("description") or ""),
        str(part.get("part_description") or ""),
    ]).upper()
    _suffix = re.search(r"\d([A-Z])$", pn)
    x_suffix = bool(_suffix and _suffix.group(1) == "X")
    return x_suffix or bool(_SPECIAL_ITEM_DESC_RE.search(desc))


_SPECIAL_ITEM_FAB_OPS = {
    "laser_cutting", "saw", "cnc", "cnc_routing", "guillotine", "punch",
    "folding", "fold", "weld", "welding", "dress_welds", "glue", "wet_spray",
    "powder_coating", "diamond_polish", "edge_banding", "bench_work",
    "hole_machining", "drilling", "linebend",
}


def _cut_method_entry(part: Dict[str, Any]) -> Dict[str, Any]:
    """The shop rule row that covers this part's material and gauge, or {}."""
    _mat = str(part.get("normalized_material") or part.get("material") or "").strip().upper()
    if not _mat:
        return {}
    _th = _safe_float(part.get("normalized_thickness_mm") or part.get("thickness_mm"))
    for _rule in (getattr(config, "CUT_METHOD_BY_MATERIAL", []) or []):
        if not isinstance(_rule, dict):
            continue
        if str(_rule.get("material") or "").strip().upper() != _mat:
            continue
        _max = _safe_float(_rule.get("max_thickness_mm"))
        if _max is not None and (_th is None or _th > _max):
            continue
        if str(_rule.get("method") or "").strip().lower() in ("laser", "punch", "router"):
            return _rule
    return {}


def _cut_method_source(part: Dict[str, Any]) -> str:
    """Whose rule decided this part's cut, for the line that says so."""
    return str(_cut_method_entry(part).get("source") or "").strip()


def _cut_method_rule(part: Dict[str, Any]) -> str:
    """Which machine SDI cuts this material on, from the shop's own written rule. "" if none.

    DELIBERATELY NOT A READ OF THE DRAWING OR THE CUT FILE. Both were tried and neither can
    answer: the DXF layer set is a fixed SolidWorks export template that names no process,
    and the model asked to infer one returned a different answer on ten consecutive runs of
    the same unchanged file. A costing decision taken from a source that cannot repeat itself
    is not a decision, it is a coin flip with a price attached.

    So this reads config.CUT_METHOD_BY_MATERIAL — a table a person maintains — and returns ""
    when it holds nothing for this material and gauge, which leaves the caller flagging the
    line rather than picking a machine.
    """
    return str(_cut_method_entry(part).get("method") or "").strip().lower()


def _weld_members(part: Dict[str, Any]) -> int:
    """How many parts this weldment joins, where the record can say. 0 when it cannot.

    Read from every spelling the pipeline files children under, because a weldment's members
    reach the record by three different routes and a reader that knows one of them counts
    zero on the other two."""
    for _field in ("child_parts", "children", "assembly_children"):
        _kids = part.get(_field)
        if isinstance(_kids, (list, tuple, set)) and len(_kids) >= 2:
            return len(_kids)
    return 0


def _weld_geometry(part: Dict[str, Any]) -> Tuple[float, int]:
    """(weld length in mm, joint count) for this part — 0 for what nothing states.

    Weld length is read only where a pack states it. The joint count is stated where a pack
    states it and DERIVED otherwise from the members being joined: a weldment of N parts has
    at least N-1 joints, which is the difference between a two-part holder and a four-member
    frame and therefore the difference between a rule and a blanket.

    Both spellings are read for each, because readers file measured facts in either."""
    _mf = part.get("manufacturing_features") or {}
    _mm = _safe_float(part.get("weld_length_mm")) or _safe_float(_mf.get("weld_length_mm")) or 0.0
    _j = _safe_int(part.get("weld_joint_count")) or _safe_int(_mf.get("weld_joint_count")) or 0
    if not _j:
        _members = _weld_members(part)
        _j = max(0, _members - 1)
    return float(_mm), int(_j)


def is_weldment_parent(part: Dict[str, Any]) -> bool:
    """Is this the weldment, rather than a part welded into one?

    TWO BOOLEANS WERE THE WHOLE GATE, AND ONE MISSING BOOLEAN COST 47 MINUTES A UNIT.

    7332-01-101 is a FRAME WELDMENT. The Provenance tab prints it as an assembly, the route
    graph gives it six children, the plating line lists its members by name — and its record
    carried neither `is_assembly_parent` nor `is_sub_assembly`. So the weld allowance the
    welding department stated, already sitting in config, never applied: the sheet booked
    2 minutes of welding and 1 of dressing against their 30 and 20, about GBP 28.57 a unit
    on a GBP 63 stand.

    The same lesson as the plating member list, which had to stop reading the parent's own
    child list and re-derive from the compiled hierarchy: ASK WHAT THE JOB SAYS THIS PART IS,
    not whether one reader happened to set one flag. Every signal here is already used
    elsewhere in the engine to mean assembly — the flags, the children, the page role, and
    config's own weldment-naming tables, which exist precisely to recognise this.

    Narrow by construction: every caller also requires a welding operation on the part, so a
    bracket nobody welds reaches none of it whatever it is called.
    """
    if part.get("is_assembly_parent") or part.get("is_sub_assembly"):
        return True
    if _weld_members(part) >= 2:
        return True
    _roles = part.get("page_roles")
    if isinstance(_roles, (list, tuple, set)) and any(
            str(r).strip().lower() in ("assembly", "sub_assembly", "weldment") for r in _roles):
        return True
    if str(part.get("kind") or "").strip().lower() in ("assembly", "weldment"):
        return True
    # config already keeps the shop's own words for this, for exactly this question.
    _desc = str(part.get("description") or "").upper()
    if _desc and any(str(tok).upper() in _desc
                     for tok in (getattr(config, "WELDMENT_PARENT_DESC_TOKENS", []) or [])):
        return True
    _pn = str(part.get("part_number") or "")
    return any(re.search(str(_sfx), _pn, re.IGNORECASE)
               for _sfx in (getattr(config, "WELDMENT_PARENT_PN_SUFFIXES", []) or []))


def _weld_time_is_an_allowance(part: Dict[str, Any], ops: Any) -> bool:
    """True when this part is welded, is an assembly, and the pack measures nothing.

    ONE PREDICATE, TWO READERS. Welding and dressing are timed ~90 lines apart and dressing
    runs FIRST, so it cannot read a flag the weld branch has not set yet. A second copy of
    the test is how a sheet comes to book 30 minutes of welding beside 1 minute of dressing.
    """
    if "welding" not in (ops or ()):
        return False
    if not is_weldment_parent(part):
        return False
    _mm, _j = _weld_geometry(part)
    return _mm <= 0 and _j <= 0


def estimate_process_times(part: Dict[str, Any], quantity: int = 1) -> Dict[str, Any]:
    geom = part.get("geometry_rollup", {})
    ops = _part_ops(part)

    # A PLATE DOES NOT FOLD — enforced HERE, at costing time, because this is the last point
    # before an op becomes money.
    #
    # The SolidWorks connector already strips the fold when the cut list reports zero bends
    # AND the solid is one thickness thick. But the connector runs early, and
    # document_builder re-derives folding from the drawing's own text ("fold or bend work
    # indicated") long afterwards — which is how 12120's 04M was back in the Fold 1.5mm
    # group after the strip had removed it. The op was removed once and grew back.
    #
    # native_flat_solid is the model's durable statement that the part is a plate, so the
    # gate can be applied again after every pass that could re-add the op has run. Removing
    # an op we know is impossible needs no arbitration: the drawing text is a cue, and the
    # solid is a measurement.
    if part.get("native_flat_solid"):
        if "folding" in ops:
            ops = [o for o in ops if o != "folding"]
        for _fld in ("textual_operations", "inferred_operations", "operations"):
            if isinstance(part.get(_fld), list) and "folding" in part[_fld]:
                part[_fld] = [o for o in part[_fld] if o != "folding"]   # precedence: direct-write ok — removes an op the model rules out
        _mf = part.setdefault("manufacturing_features", {})
        if isinstance(_mf, dict):
            _mf["bend_count"] = 0
        _rf = part.get("risk_flags")
        if isinstance(_rf, list):
            _rf[:] = [f for f in _rf
                      if "fold" not in str(f).lower() and "bend" not in str(f).lower()]
    # Special / bought-in finishing items (tiles, mosaics, graphics, vinyl, -X suffix):
    # strip all fabrication ops — they are bought in, not made. Handling is retained so
    # the item is still received/assembled; pricing routes through the bought-in path.
    if _is_special_bought_in_item(part):
        ops = [o for o in ops if o not in _SPECIAL_ITEM_FAB_OPS]
        for _op_field in ("textual_operations", "inferred_operations"):
            if isinstance(part.get(_op_field), list):
                part[_op_field] = [o for o in part[_op_field] if o not in _SPECIAL_ITEM_FAB_OPS]   # precedence: direct-write ok — removes ops, adds no evidence
        _roles = [str(r).lower() for r in (part.get("page_roles") or [])]
        if "bought_in" not in _roles:
            part.setdefault("page_roles", []).append("bought_in")
        part["special_finish_item"] = True
    manufacturing_features = part.get("manufacturing_features", {})
    geometry_confidence = 0.0
    if isinstance(geom.get("confidence"), dict):
        geometry_confidence = geom["confidence"].get("geometry_reliability", 0.0) or 0.0

    dims_pm = infer_primary_dimensions(part)
    blank_length_pm, blank_width_pm = estimate_blank_size(dims_pm)

    raw_cut_length_mm = manufacturing_features.get("raw_cut_length_mm", geom.get("estimated_cut_length_mm", 0.0) or 0.0)
    cut_length_mm = manufacturing_features.get("cut_length_mm", raw_cut_length_mm * max(0.25, geometry_confidence) if raw_cut_length_mm else 0.0)
    pierces = geom.get("estimated_pierce_count", 0) or 0
    holes = max(
        int(manufacturing_features.get("hole_count") or 0),
        int(geom.get("estimated_hole_count") or 0),
        int(geom.get("estimated_pierce_count") or 0),
        len(part.get("hole_sizes_mm", []) or []),
    )
    # A MEASURED ZERO IS A VALUE. Where the model was read and found no bends, that answer
    # stands and nothing falls through to the drawing. Everywhere else the fold-shadowing fix
    # applies unchanged: a present-but-zero bend_count from something that cannot see bends
    # falls through to PDF fold evidence, so parts folded from callouts alone still fold.
    if _model_measured_zero_bends(part):
        bends = 0
    else:
        # THE ONE RESOLVER, ASKED BY THE THING THAT SPENDS THE MONEY. `fold_count` ranks the
        # flat pattern's measured bend axes above the drawing's fold callouts, both above the
        # SolidWorks feature count, and all three above our own dashed-line inference. Asked
        # here rather than re-derived, so the charged fold and the fold the sheet NAMES cannot
        # be two different numbers -- which is what 401912-02 shipped: three charged, and a
        # provenance label from the flat pattern that had said one.
        from fold_count import press_brake_folds as _press_folds      # noqa: PLC0415
        _fold_res = _press_folds(part)
        bends = _fold_res["count"] or (
            manufacturing_features.get("bend_count")
            or max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])),
                   part.get("fold_count_textual", 0) or 0))
    bend_length_mm = sum([_safe_float(value) or 0.0 for value in part.get("fold_values_mm", [])])
    thickness_mm = _safe_thickness_mm(part)

    # SDI Intelligence — infer a cutting operation when the drawing text did not
    # name one. Any sheet/board part with a cut length MUST be cut somehow, so
    # assign laser cutting (steel + acrylic are laser cut at SDI). Without this,
    # parts with valid flat-pattern geometry got zero operations -> zero labour.
    _mat_u = str(part.get("normalized_material") or "").upper()
    _SHEET_METALS = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                     "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}
    _CUT_BOARDS = {"ACRYLIC", "POLYCARBONATE", "PETG", "HIPS", "MDF", "VENEERED_MDF",
                   "OAK_VENEER_MDF", "PLYWOOD", "BIRCH_PLYWOOD", "HDPE_PLASTIC",
                   "FOAMEX", "DIBOND", "TIMBER"}
    _CUTTING_OPS = ("laser_cutting", "cnc_routing", "cnc", "punch", "guillotine", "saw")
    _has_cut_op = any(o in ops for o in _CUTTING_OPS)

    # SDI Intelligence — metal holes are LASER-CUT, not a separate hole/drill op. Tim's
    # sheets have no metal hole op (only "Drill (Acrylic)"); job 1282 (all metal) carries
    # none. But a metal part with holes can arrive with a stale hole_machining/drilling in
    # textual_operations (from the note/geometry extractor), which then gets costed -> a
    # wrong Guillotine line on the sheet. Strip it from BOTH the costing ops and the part's
    # displayed textual_operations, for sheet-metal only. Acrylic/board KEEP drilling.
    # Broadened metal gate: normalized_material may not be set yet at this point in the
    # pipeline (seen None on 1298-01 while the raw `materials` list already held MILD STEEL),
    # which silently skipped the strip. Check ALL material fields so a not-yet-normalized
    # part is still recognised as sheet metal. Acrylic/board won't match on any field.
    _mat_fields = [_mat_u]
    _mat_fields.append(str(part.get("material") or "").upper())
    for _m in (part.get("materials") or []):
        _mat_fields.append(str(_m or "").upper().replace(" ", "_"))
        _mat_fields.append(str(_m or "").upper())
    _is_metal_any = any(mf in _SHEET_METALS for mf in _mat_fields if mf)
    if _is_metal_any:
        _metal_hole_ops = ("hole_machining", "drilling")
        ops = [o for o in ops if o not in _metal_hole_ops]
        if isinstance(part.get("textual_operations"), list):
            part["textual_operations"] = [
                o for o in part["textual_operations"] if o not in _metal_hole_ops
            ]
        if isinstance(part.get("inferred_operations"), list):
            part["inferred_operations"] = [
                o for o in part["inferred_operations"] if o not in _metal_hole_ops
            ]
    # diamond_polish is an acrylic-EDGE finishing op — steel is never diamond polished
    # (it is linished/dressed). It leaks onto steel because the standard drawing boilerplate
    # "CHROME PLATING - POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH" sits on every page
    # and the op-detector reads "POLISH", booking large spurious DPOL lines (e.g. £83 on a
    # powder-coated base mesh, £32 on a base shelf). Strip it from metal parts unless the
    # part's OWN finish explicitly calls a mirror / diamond polish. Acrylic parts are not
    # metal, so they are unaffected here and still get DPOL via the acrylic route below.
    # General de-pollution, same class as the material-boilerplate fix — not a per-job patch.
    if _is_metal_any and "diamond_polish" in ops:
        _fin_all = " ".join([
            str(part.get("normalized_finish") or ""),
            " ".join(str(f) for f in (part.get("surface_finishes") or [])),
            str(part.get("finish") or ""),
        ]).upper()
        _genuine_polish = ("MIRROR" in _fin_all) or ("DIAMOND POLISH" in _fin_all)
        if not _genuine_polish:
            ops = [o for o in ops if o != "diamond_polish"]
            for _op_field in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_op_field), list):
                    part[_op_field] = [o for o in part[_op_field] if o != "diamond_polish"]   # precedence: direct-write ok — removes ops, adds no evidence
    # Section/tube/wire parts without a flat DXF are SAWN/MITRED to length, not laser
    # profile-cut. Their PDF "cut length" is the whole-GA-page geometry rollup (e.g.
    # 24,508mm on a 600mm frame), so it must never drive laser cost or trigger a laser
    # op. The DXF guard means any section that DOES carry a flat pattern is left alone.
    _section_no_dxf = (
        _is_section_or_wire_candidate(part, part.get("normalized_material"))
        and not _dxf_geometry_trusted(part, part.get("normalized_geometry", {}) or {})
    )
    # SDI buys the RHS/tube as a length (does NOT make it) -> no in-house cut, neither
    # laser profile nor saw. But SDI DOES bend the tube, so the bend op is RETAINED.
    # Material = bought-in length; cost = material + bend + finish + handling.
    if _section_no_dxf:
        ops = [o for o in ops if o not in ("laser_cutting", "saw")]
        if isinstance(part.get("inferred_operations"), list):
            part["inferred_operations"] = [
                o for o in part["inferred_operations"] if o not in ("laser_cutting", "saw")
            ]
        # Also correct the part's DISPLAYED operations so the workbook / decision report
        # don't show "laser_cutting" on a tube that is bought as a length and never lasered.
        # (Previously only the local `ops` used for labour was stripped, leaving the part's
        # textual_operations stale and misleading in the output sheet.)
        if isinstance(part.get("textual_operations"), list):
            part["textual_operations"] = [
                o for o in part["textual_operations"] if o not in ("laser_cutting", "saw")
            ]
        part["section_costing_adjustment"] = {
            "rule": "section_bought_as_length_bent_inhouse",
            "basis": "bought_in_length_plus_bend_finish_handling",
            "note": "RHS/tube bought as a length (not made in-house) -- no cut/saw. SDI "
                    "bends the tube, so the bend op is retained; the bend COUNT may be "
                    "under-read from the drawing -- verify bend count/time with the tube-bend "
                    "operator. Coated in-house (SDI sprays everything).",
        }
    if not _has_cut_op and cut_length_mm and cut_length_mm > 0 and not _section_no_dxf:
        if _mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS:
            ops = list(ops) + ["laser_cutting"]
            record_operation(part, "laser_cutting", "inference")
    # Every fabricated part also needs handling/assembly time at the bench.
    if (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS) and "handling" not in ops:
        ops = list(ops) + ["handling"]
        # 12120's shadow reported THIRTEEN handling decisions at `unknown 0`. This is why:
        # handling was added to the local costing list and never to the record, so it
        # reached the compiler with no provenance at all.
        record_operation(part, "handling", "inference")

    # ── BOUGHT-IN PARTS TAKE NO FABRICATION LABOUR ───────────────────────────────
    # Runs before every route rule below, because a purchased component is not a routing
    # question at all. The UPC sticker was a catalogue line on the BOM and, at the same
    # time, a record carrying weld, powder and glue on the route — the same item classified
    # twice, at different stages, with different answers. Identity is settled once here.
    #
    # Handling/assembly is deliberately NOT stripped: we do fit bought-in components, and
    # that bench time is real work that must keep being charged.
    try:
        from bought_in_policy import (bought_in_conflict, is_bought_in,
                                      strip_fabrication_ops)
        if is_bought_in(part):
            _bi_removed = strip_fabrication_ops(part)
            _bi_ops = set(part.get("textual_operations") or [])
            ops = [o for o in ops if o in _bi_ops or str(o).lower() in ("handling", "assembly")]
            if _bi_removed:
                part.setdefault("review_flags", []).append(
                    f"bought-in part — fabrication operations removed "
                    f"({', '.join(_bi_removed)}). We buy this item; only handling/assembly "
                    f"time applies. Price it from the catalogue, not from a route")
            if bought_in_conflict(part):
                # Identity says buy, geometry says make. Do not let the engine pick a side.
                part.setdefault("review_flags", []).append(
                    "CONFLICT: classified bought-in, but the part also carries its own "
                    "measured flat pattern. One of the two is wrong — confirm whether this "
                    "is a purchased item or one we fabricate")
    except Exception:
        pass

    # WELDING IS A METAL PROCESS. Timber, board and plastic parts are glued, screwed or
    # solvent-bonded — never CO2/MIG welded. The weld op leaks onto joinery the same way
    # diamond polish leaked onto steel: a weld note somewhere in the drawing text (an
    # assembly instruction, a spec block, a neighbouring detail) is read as a cue for the
    # part, and because `welding` automatically chains `dress_welds` below, ONE bad cue
    # books TWO departments. On the Horti Crate — a wooden crate — that was Weld (CO2)
    # plus Dress Welds against parts the engine itself had identified as TIMBER.
    #
    # Gated on POSITIVE evidence the part is non-metal (a named board/timber/plastic
    # family), the same standard as the polish gate, so a part whose material has not been
    # resolved yet is left alone rather than stripped on a guess. Where the material is
    # genuinely mis-read the fix belongs upstream in the material read, not here.
    _is_board_any = any(mf in _CUT_BOARDS for mf in _mat_fields if mf)
    if _is_board_any and not _is_metal_any:
        _weld_ops = ("welding", "dress_welds", "spot_welding", "resistance_welding")
        _stripped = [o for o in ops if o in _weld_ops]
        if _stripped:
            ops = [o for o in ops if o not in _weld_ops]
            for _op_field in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_op_field), list):
                    part[_op_field] = [o for o in part[_op_field] if o not in _weld_ops]   # precedence: direct-write ok — removes ops, adds no evidence
            part.setdefault("review_flags", []).append(
                f"{'/'.join(_stripped)} removed: part is {_mat_u or 'a board/timber family'}, "
                f"which is not welded — joining is by glue/fixings. A weld cue was read from "
                f"the drawing text; confirm it belongs to a different (metal) part")
            # Clear the weld SIGNALS too, not just the costed ops. welding_required is
            # synthesised from textual_operations back at document-build time, so without
            # this the sheet correctly shows no weld while the job report still tells the
            # estimator to "verify weld/dress content" on the same part. A report that
            # contradicts the sheet it accompanies is worse than either alone.
            _mf_w = part.get("manufacturing_features")
            if isinstance(_mf_w, dict):
                _mf_w["welding_required"] = False
            if isinstance(part.get("risk_flags"), list):
                part["risk_flags"] = [f for f in part["risk_flags"] if f != "weld_required"]

    # DRES — a structural (CO2/WELD) weld is dressed/linished to clean the bead before
    # finishing. Chain a dress_welds op after the welding op so the DRES dept labour
    # lands on the route (timing set in the run/setup tables below). Config-gated; spot/
    # resistance welds leave no proud bead and are not dressed, so only `welding` triggers.
    #
    # AND THE CUSTOMER'S OWN STANDARD DECIDES WHETHER THE LINE EXISTS. "M&S dress all seen
    # welds; TTI none" — Howard Thurley, 15 Sep 2026 — is a fact about the customer, not
    # about a job, and it governs the engine's INFERENCE only: a drawing that states
    # dressing outright is never overruled by a customer default. estimate_document stamps
    # the standard (_customer_finish_standard) from the same customer name the workbook
    # header prints; a customer not in the table keeps the shop default exactly as before.
    _cfs = part.get("_customer_finish_standard")
    if (
        getattr(config, "DRESS_AFTER_STRUCTURAL_WELD", True)
        and "welding" in ops
        and "dress_welds" not in ops
    ):
        if isinstance(_cfs, dict) and _cfs.get("dress_visible_welds") is False:
            part.setdefault("review_flags", []).append(
                f"weld dressing NOT charged: {_cfs.get('customer')}'s own standard is no "
                f"weld dressing — '{_cfs.get('statement')}' "
                f"({_cfs.get('stated_by')}, {_cfs.get('stated_on')}). A customer rule "
                f"governing the engine's inference; a drawing that states dressing would "
                f"still be charged")
        else:
            ops = list(ops) + ["dress_welds"]
            record_operation(part, "dress_welds", "override_rule")
            if isinstance(_cfs, dict) and _cfs.get("dress_visible_welds") is True:
                part.setdefault("review_flags", []).append(
                    f"weld dressing charged per {_cfs.get('customer')}'s own standard — "
                    f"'{_cfs.get('statement')}' ({_cfs.get('stated_by')}, "
                    f"{_cfs.get('stated_on')})")

    setup_times_min: Dict[str, float] = {}
    run_times_min: Dict[str, float] = {}
    powder_coating_detail: Optional[Dict[str, Any]] = None

    _is_wire_op_part = any(
        op in ops
        for op in ("wire_forming", "welding", "resistance_welding", "spot_welding", "deburring")
    )

    # SDI Intelligence — punch recognition. A dense field of holes (e.g. a peg
    # panel: 380+ identical small holes) is a PUNCH job, not laser. Pricing every
    # hole as a 1.2s laser pierce massively over-costs these parts. Swap an
    # assigned/inferred laser op for punch so the holes cost as hits, not pierces.
    _punch_blob = " ".join([
        str(part.get("description") or ""),
        str(part.get("part_number") or ""),
        ";".join(part.get("process_notes") or []),
    ]).upper()
    # Recognise on the geometry pierce/hole count (DXF truth, e.g. 386), not the
    # manufacturing "hole_count" field, which can collapse to distinct-size count.
    _punch_hole_signal = int(max(holes or 0, pierces or 0))
    if (_mat_u in _SHEET_METALS) and "punch" not in ops and _is_punch_part(part, _punch_hole_signal, _punch_blob):
        ops = [o for o in ops if o != "laser_cutting"] + ["punch"]
        record_operation(part, "punch", "inference")

    # Known peg-family panels carry a measured machine cycle time; force punch
    # (drop laser) so the calibrated time below replaces the collapsed hit model.
    _punch_cycle = _peg_family_punch_cycle(part)
    if _punch_cycle is not None:
        ops = [o for o in ops if o != "laser_cutting"]
        if "punch" not in ops:
            ops = ops + ["punch"]
        record_operation(part, "punch", "inference")

    if "laser_cutting" in ops:
        rule = LABOUR_RULES["laser_cutting"]
        setup_times_min["laser_cutting"] = round(rule["setup_min"], 2)
        speed_table = rule.get("cutting_speeds_mm_per_sec", {})
        if speed_table:
            speed_key = min(speed_table.keys(), key=lambda key: abs(float(key) - (thickness_mm or 1.0)))
            cutting_speed = float(speed_table[speed_key])
        else:
            cutting_speed = 80.0
        # For section parts without a flat DXF, charge a realistic cut-to-length using
        # the inferred stock length, not the phantom PDF perimeter. Stamp the adjustment
        # so the inferred basis is visible downstream rather than silently applied.
        _laser_cut_length_mm = cut_length_mm
        if _section_no_dxf:
            _stock_len = _infer_section_length_mm(part)
            _laser_cut_length_mm = min(cut_length_mm, _stock_len) if (_stock_len and _stock_len > 0) else 0.0
            part["section_costing_adjustment"] = {
                "rule": "section_no_flat_dxf",
                "laser_basis": "cut_to_length",
                "pdf_cut_length_mm": round(cut_length_mm, 1),
                "applied_cut_length_mm": round(_laser_cut_length_mm, 1),
                "note": "Tube/section sawn to length, not laser profile-cut. "
                        "Cut length INFERRED from stock length — verify manually.",
            }
        load_unload_sec = float(rule.get("load_unload_sec", 0.0))
        profile_cutting_sec = (_laser_cut_length_mm / cutting_speed) if cutting_speed > 0 else 0.0
        pierce_sec = pierces * float(rule["pierce_sec_each"])
        run_times_min["laser_cutting"] = round((load_unload_sec + profile_cutting_sec + pierce_sec) / 60.0, 2)

    if "punch" in ops:
        prule = LABOUR_RULES.get("punch", {}) or {}
        setup_times_min["punch"] = round(float(prule.get("setup_min", 3.0)), 2)
        load_unload = float(prule.get("load_unload_sec", 30.0))
        sec_per_hit = float(prule.get("sec_per_hit", 0.7))
        profile_speed = float(prule.get("profile_speed_mm_per_sec", 60.0))
        hit_count = int(max(holes, pierces) or 0)
        # Outline only (perimeter), NOT cut_length — cut_length includes hole edges
        # that are single punch hits here, so using it would double-count.
        _perim = 2.0 * ((blank_length_pm or 0.0) + (blank_width_pm or 0.0))
        profile_sec = (_perim / profile_speed) if profile_speed > 0 else 0.0
        run_times_min["punch"] = round((load_unload + hit_count * sec_per_hit + profile_sec) / 60.0, 2)
        if _punch_cycle is not None:
            run_times_min["punch"] = round(_punch_cycle[0], 2)
            part["punch_calibration"] = {"cycle_min": round(_punch_cycle[0], 2), "basis": _punch_cycle[1]}

    if "hole_machining" in ops:
        rule = LABOUR_RULES["hole_machining"]
        setup_times_min["hole_machining"] = round(rule["setup_min"], 2)
        run_times_min["hole_machining"] = round((holes * rule["sec_per_hole"]) / 60.0, 2)

    # ---- THINGS THE SHOP KNOWS THAT THE DRAWING DOES NOT SAY --------------------
    # (The 0.9 mm gauge substitution used to be flagged here as TBC. Howard confirmed the
    #  practice on 15 Sep, so it is now a RULE — config.PRODUCTION_MATERIAL_SUBSTITUTIONS,
    #  applied by apply_production_substitutions at the top of estimate_part, before the
    #  mass and the laser speed read the gauge. The flag lives with the rule.)
    #
    # "Line 85 – Drawing doesn't annotate – material is brushed prior to sending to platers,
    # op. for Manual Labour (Metal) 40 Minutes – Grey area as drawing only nominates a finish
    # as Harrods01." Real work, worth real money, and stated nowhere on the pack. Not added:
    # named, so a person decides whether this job carries it.
    # AND IT IS COSTED NOW, BECAUSE HE TOLD US IT HAPPENS.
    #
    # The paragraph above called the flag "the only honest third option". It was not. A flag
    # nobody could read is not a third option, it is the second one with extra steps — and
    # grepping the 20:26 book proved it reached neither deliverable. The estimator has stated
    # a real operation with a real duration; leaving it off the sheet is under-charging, and
    # under-charging is the direction nobody notices.
    #
    # ONCE PER CONSIGNMENT, NOT ONCE PER MEMBER. What goes to the platers is the weldment.
    # Booking 40 minutes against each of 7332-01-101's six members would be four hours of
    # linishing on one stand, which is how a defensible figure becomes an absurd one. So it
    # lands on the part the plating line actually plates.
    #
    # THE LIMIT, SAID OUT LOUD: a plated LEAF with no weldment above it gets the flag and no
    # charge, exactly as before. That job is under-charged by this operation and the line
    # says so rather than the engine guessing at a part it has never been given a figure for.
    if _is_plate_finish(_part_finish_text(part)) or named_plate_spec(_part_finish_text(part)):
        _bb = getattr(config, "BRUSH_BEFORE_PLATE", {}) or {}
        # PER UNIT — Howard's own answer, 16 Sep: "40 Minutes was given by production for
        # one unit". It read per-consignment, which at six off understated it six-fold.
        _bb_min = _safe_float(_bb.get("minutes_per_unit")) or 0.0
        _bb_op = str(_bb.get("operation") or "manual_labour_metal")
        if (_bb.get("enabled") and _bb_min > 0 and is_weldment_parent(part)
                and not part.get("brush_before_plate_applied")):
            part["brush_before_plate_applied"] = True
            ops = list(ops) + ([_bb_op] if _bb_op not in ops else [])
            run_times_min[_bb_op] = round(
                float(run_times_min.get(_bb_op, 0.0)) + _bb_min, 2)
            setup_times_min.setdefault(_bb_op, float(_bb.get("setup_min", 0.0)))
            record_operation(part, _bb_op, "override_rule")
            # AND WHAT THE FIGURE IS BOUNDED BY. Howard gave 40 minutes "based on
            # experience and for similar size units, time would vary per unit / size", so
            # the line carries that caveat and this weldment's own measured size, which is
            # what lets him tell at a glance whether his figure travels to it.
            _bb_size = ""
            try:
                _me = part.get("material_estimate") or {}
                _l = _safe_float(_me.get("blank_length_mm"))
                _w = _safe_float(_me.get("blank_width_mm"))
                _kg = _safe_float(part.get("normalized_weight_kg")
                                  or _me.get("stated_weight_kg"))
                if _l and _w:
                    _bb_size = f" This weldment measures {_l:g} x {_w:g} mm."
                elif _kg:
                    _bb_size = f" This weldment weighs about {_kg:g} kg."
            except Exception:                                    # noqa: BLE001
                _bb_size = ""
            part.setdefault("review_flags", []).append(
                f"brushed before plating: {_bb_min:g} min of "
                f"{_bb_op.replace('_', ' ')} PER UNIT on this weldment before it goes to "
                f"the platers. THE DRAWING DOES NOT ANNOTATE THIS — it is the shop's "
                f"practice as stated by the estimator ({_bb.get('source', 'shop figure')}). "
                f"AN INDICATIVE FIGURE, NOT A CONSTANT: "
                f"{_bb.get('basis', 'stated for one job')}, calibrated on "
                f"{_bb.get('calibrated_on') or 'one stand'}.{_bb_size} Confirm it applies "
                f"to this finish and to a unit this size, or take it off")
        elif not part.get("_brush_before_plate_flagged"):
            part["_brush_before_plate_flagged"] = True
            part.setdefault("review_flags", []).append(
                "plated part: the shop brushes material before it goes to the platers — "
                f"about {_bb_min or 40:g} minutes of Manual labour (Metal) per the estimator "
                "— and this part is not the weldment that goes in the tank, so it is NOT "
                "costed here. Confirm whether this finish needs it")

    # ---- A TUBE IS ONLY BENT IF SOMETHING SAYS IT BENDS --------------------------
    # "Line 103 - Tube Bending Op. – Not Required." 7332-01-002 booked two tube bends on a
    # leg that is straight. tube_bending is not inferred from geometry the way folding is —
    # it arrives from the drawing read, so a mention near a tube is enough to charge the
    # tube-bender, its £32.84 rate and its 45-minute set-up.
    #
    # The same standard the fold gate already applies: drawing evidence infers a bend, and
    # the absence of any bend at all rules one out. Bend count, a bend line measured off a
    # DXF, an angle callout, a textual fold count — any one of them keeps the op. None of
    # them, and the part is straight and the op comes off, said out loud rather than
    # silently. A part with no tube-bending op on it is untouched.
    # Howard's ruling closed the loop on -002 — "Line 103 - Tube Bending Op. – Not
    # Required" — and named the physics: the tube-bender wraps ROUND/OVAL tube around a
    # former, to a RADIUS. A square leg with 45° callouts is a MITRED cut, not a bend; the
    # angles describe the saw, and reading them as bend evidence is exactly how -002 booked
    # two bends on a straight leg. So the section's own shape now speaks: a square/rect
    # section whose only evidence is angle callouts loses the op, while measured bends, a
    # radius on a round section, and a plain textual bend statement keep their standing.
    _tube_bend_ops = [o for o in ops if str(o).strip().lower() in
                      ("tube_bending", "tubebend", "tube_bend")]
    if _tube_bend_ops:
        _ss_tb = part.get("section_stock") or {}
        _round_tb = str(_ss_tb.get("profile_form") or "").upper() in (
            "CHS", "EHS", "OVAL", "ROUND")
        _square_tb = (not _round_tb) and bool(
            _safe_float(_ss_tb.get("a")) and _safe_float(_ss_tb.get("b")))
        # MEASURED means measured. `bends` above folds angle callouts and textual counts
        # into one figure, so it cannot distinguish a measurement from a word — only a
        # DXF bend line or the model's own bend count is a measurement here.
        _measured_tb = (
            (_safe_int(part.get("bend_count_dxf")) or 0) > 0
            or (_safe_int((part.get("manufacturing_features") or {}).get("bend_count")) or 0) > 0)
        _radius_tb = len(part.get("radii_mm") or []) > 0
        _angles_tb = len(part.get("angles_deg") or []) > 0
        _worded_tb = (_safe_int(part.get("fold_count_textual")) or 0) > 0
        if _measured_tb or (_round_tb and _radius_tb):
            _keep_tb, _why_tb = True, ""
        elif _square_tb and _angles_tb and not _worded_tb:
            _keep_tb = False
            _why_tb = (f"tube bending removed: this is a "
                       f"{_ss_tb.get('a')}x{_ss_tb.get('b')} square/rect section and the "
                       f"only bend evidence is angle callouts — on a straight mitred leg "
                       f"those describe the SAW CUT, not a bend, and the tube-bender "
                       f"wraps round/oval tube to a radius (Howard Thurley, 7332-01: "
                       f"'Tube Bending Op. – Not Required'). If it does bend, the drawing "
                       f"needs a radius or a bend line")
        elif not (_angles_tb or _worded_tb or _radius_tb):
            _keep_tb = False
            _why_tb = ("tube bending removed: nothing on this part states a bend — no "
                       "bend count, no bend line in a DXF, no radius, no angle callout. "
                       "The op was read from the drawing text near a tube, and a straight "
                       "leg does not go on the tube-bender. If it does bend, the drawing "
                       "needs to say so")
        else:
            # KEPT, AND STILL WORTH ASKING ABOUT. The drawing did say something — a bend
            # word, an angle on a round or unknown section, a radius with no shape to hang
            # it on — and nothing measured it. A word is weaker evidence than a
            # measurement, and the tube-bender is £32.84 an hour with a 45-minute set-up,
            # so the weak case is worth a sentence. It is NOT worth a silent deletion:
            # removing charged work because one estimator disagreed with one drawing is
            # how a rule stops describing anything. Charged as read; a person rules.
            _keep_tb = True
            _why_tb = (f"tube bending CHARGED on the drawing's word alone: something "
                       f"states a bend but nothing measures one — no bend line in a DXF, "
                       f"and the bender needs a round/oval section and a radius "
                       f"({'round section, no radius' if _round_tb else 'section shape unread'}). "
                       f"{len(_tube_bend_ops)} tube-bend op(s) at the bender's rate and "
                       f"set-up. Confirm the leg actually bends, or take the op off")
        if not _keep_tb:
            ops = [o for o in ops if o not in _tube_bend_ops]
            for _tf in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_tf), list):
                    part[_tf] = [o for o in part[_tf]                    # precedence: direct-write ok — removes ops, adds no evidence
                                 if str(o).strip().lower() not in
                                 ("tube_bending", "tubebend", "tube_bend")]
            for _timing in (setup_times_min, run_times_min):
                for _o in _tube_bend_ops:
                    _timing.pop(_o, None)
            part.setdefault("removed_operations", []).extend(_tube_bend_ops)
            # AND THE RULING HAS TO TRAVEL, OR THE SHEET RE-ADDS WHAT THIS JUST REMOVED.
            #
            # Stripping ops/textual/inferred and the timings cleans the COSTED record. The
            # route is a different record: wb_populate.route_operations_by_part rebuilds the
            # operation list from summary["parts"], and route_compiler builds its claims from
            # the same place. Both already honour one name for a ruling — operations_ruled_out
            # — and this gate was writing another, removed_operations. Two names for one fact,
            # so the leg came back to the sheet with its Tubebend intact: TBEN at its own rate
            # with a 45-minute set-up, on a straight leg, after the engine had ruled it out.
            #
            # Recorded under the name the readers actually read, with the reason attached so
            # the cancellation can be explained rather than merely obeyed. removed_operations
            # stays as the human-facing list it always was; this is the machine-facing one.
            _ruled = part.setdefault("operations_ruled_out", {})
            for _o in _tube_bend_ops:
                _ruled.setdefault(_o, _why_tb)
            part.setdefault("review_flags", []).append(_why_tb)
        elif _why_tb:
            part.setdefault("review_flags", []).append(_why_tb)

    # ---- THE LAMINATE IS IN THE BOARD, SO IT IS NOT ALSO A SHOP OPERATION ----------
    #
    # THE SHOP DOES NOT LAMINATE; THE MERCHANT DOES — and the moment the board is promoted
    # to its faced family, the facing has been PAID FOR IN THE SHEET PRICE. The route still
    # carried `laminating`, which department_codes sends to GLUE, so 11908-21's 15:50 book
    # charged it twice: once inside whatever the board costs, and again as £18.43 a unit of
    # glue labour at 40/hr with a half-hour set-up. Both lines are individually plausible,
    # which is what makes the double survive a reading.
    #
    # Scoped to the promotion and nothing else. A part that really IS laminated in the shop
    # — a core the shop lays up itself — has no `_laminate_in_board` stamp and keeps its
    # operation and its glue time exactly as before.
    #
    # THE EVIDENCE IS DELIBERATELY LEFT ON THE PART. The tube-bend gate above strips
    # `textual_operations` as well; this must not, because `_faced_board_promotion` reads
    # that very list to decide the part is faced at all. Stripping it would delete the
    # reason the board was promoted, and a second costing pass would un-promote the part
    # and put it back on raw-core money. The route readers — wb_populate and route_compiler
    # — honour `operations_ruled_out`, so the ruling travels by the name they read.
    if part.get("_laminate_in_board"):
        _lam_words = ("laminating", "lamination", "laminate", "laying_up", "lay_up")
        _lam_ops = [o for o in ops if str(o).strip().lower() in _lam_words]
        if _lam_ops:
            _why_lam = (
                "laminating removed from the route: this board is bought PRE-FACED, so the "
                "lamination is in the sheet price and charging it again as glue labour "
                "bills the same facing twice. The operation stays on the record as the "
                "evidence that the board is faced — it is the route that is cancelled, not "
                "the reading. If the shop really does lay this panel up itself, the board "
                "is not pre-faced and the material line is the thing to correct.")
            ops = [o for o in ops if o not in _lam_ops]
            for _timing in (setup_times_min, run_times_min):
                for _o in _lam_ops:
                    _timing.pop(_o, None)
            part.setdefault("removed_operations", []).extend(_lam_ops)
            _ruled_lam = part.setdefault("operations_ruled_out", {})
            for _o in _lam_ops:
                _ruled_lam.setdefault(_o, _why_lam)
            part.setdefault("review_flags", []).append(_why_lam)

    # ---- ONE BLANK IS CUT OUT ONCE ------------------------------------------------
    #
    # Laser and CNC router are two ways of cutting the SAME profile out of the SAME sheet.
    # Charging both bills the cut twice, and it is the kind of double that survives review
    # because each line is individually plausible: 12349-02-69-06A, a 5 mm acrylic front
    # cover, is in the 5 mm laser group AND carries its own CNC line at £6.81.
    #
    # THE CUT FILE ALREADY SAID WHICH. The DXF interpretation reads the layers and names a
    # recommended process — "router" for 06A — and nothing consulted it. So it is consulted:
    # the named process keeps its op and the other comes off, out loud, with the file that
    # settled it. Where the file names a combination, or names nothing, BOTH STAY and the
    # line is flagged instead, because a part can genuinely be profiled one way and pocketed
    # another and this rule must not be the thing that decides that silently.
    #
    # PER PART, WHICH IS THE WHOLE OF ITS SAFETY. An assembly that carries CNC while its own
    # flats carry laser is the correct shape — 01A takes glue and routing, its seven flats
    # take the laser — and nothing here touches it: neither part has both ops. A part with
    # one cutting op is untouched too.
    _LASER_OPS = ("laser_cutting", "laser", "punch", "punching")
    _ROUTER_OPS = ("cnc_routing", "cnc", "cnc_machining", "cnc_joinery", "pin_router", "router")
    _laser_on = [o for o in ops if str(o).strip().lower() in _LASER_OPS]
    _router_on = [o for o in ops if str(o).strip().lower() in _ROUTER_OPS]
    if _laser_on and _router_on:
        # NOT FROM THE DXF INTERPRETER. This keyed on `recommended_process` for one commit,
        # and the runner's own log is the refutation: the SAME FILE, unchanged, comes back
        #
        #   06A: laser · laser · laser · router · laser · router · laser · router · router
        #
        # across ten runs. It is a model being asked which machine and guessing, and SDI's
        # cut files cannot tell it — the layer set is a fixed SolidWorks export template
        # (SLD-0, BENDLINES, ETCHING, RIB, C_SNK, REBATE, LANCEFORM) and not one layer names
        # a process. Keyed on that, this rule would have stripped the laser on some runs and
        # the router on others, on the same pack: a visible double charge turned into an
        # invisible coin flip, which is worse than what it replaced.
        #
        # So the decision comes from a rule somebody wrote down, or it is not made here at
        # all. CUT_METHOD_BY_MATERIAL is the shop's own practice, keyed on material and
        # gauge, reproducible, and empty until the shop fills it — an absent entry flags the
        # line for a person rather than picking one.
        _named = _cut_method_rule(part)
        _drop: List[str] = []
        _kept = ""
        if _named in ("router",):
            _drop, _kept = list(_laser_on), "router"
        elif _named in ("laser", "punch"):
            _drop, _kept = list(_router_on), _named
        if _drop:
            ops = [o for o in ops if o not in _drop]
            for _tf in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_tf), list):
                    part[_tf] = [o for o in part[_tf] if o not in _drop]   # precedence: direct-write ok — removes ops, adds no evidence
            for _timing in (setup_times_min, run_times_min):
                for _o in _drop:
                    _timing.pop(_o, None)
            part.setdefault("removed_operations", []).extend(_drop)
            part.setdefault("review_flags", []).append(
                f"{', '.join(_drop)} removed: this blank was charged BOTH a laser cut and a "
                f"routed cut, which is the same profile paid for twice. SDI's own rule for "
                f"this material and gauge is '{_kept}' "
                f"({_cut_method_source(part) or 'config.CUT_METHOD_BY_MATERIAL'}), so that "
                f"one is costed. If the drawing or the issued CAM calls for the other on "
                f"this part, say so and both go back on")
        else:
            part.setdefault("review_flags", []).append(
                f"CUT TWICE? This part carries both a laser cut and a routed cut "
                f"({', '.join(_laser_on + _router_on)}) — usually the same profile costed "
                f"twice, and it is the shop that knows which machine. Nothing has been "
                f"removed: the cut file cannot say (SDI's DXF layers are a fixed export "
                f"template and name no process) and config.CUT_METHOD_BY_MATERIAL holds no "
                f"rule for this material and gauge. Put one there and every job answers it")

    # ---- Fold operation inference (general, evidence-based) ----------------------
    # A part folds if it carries fold evidence — PDF callouts (UP/DOWN + angle -> angles_deg
    # / fold_count_textual), a DXF BENDLINES bend count, or textual bend mentions — even when
    # the extractor did not emit "folding" in textual_operations (folds often live ONLY in the
    # PDF, not a DXF layer). Add the op so it is costed. Same shape as the laser/punch
    # inference above. Sheet metal / board ONLY: a tube is bent on a tubebender (its own op),
    # a bought section is not press-folded. Uses `bends` (already set from PDF fold evidence).
    # ...unless the model counted this part's bends and found none. This is the block that
    # actually put 'folding' back on 04M — it reads len(angles_deg) > 0, and the PDF carries a
    # 30-degree callout — writing it into inferred_operations, where the earlier strip had
    # already been and gone. Drawing evidence infers a fold; a measurement rules one out.
    if ("folding" not in ops and (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS)
            and not _section_no_dxf and not _model_measured_zero_bends(part)):
        _fold_evidence = (
            (bends or 0) > 0
            or len(part.get("angles_deg") or []) > 0
            or int(part.get("fold_count_textual") or 0) > 0
            or int((part.get("manufacturing_features") or {}).get("bend_count") or 0) > 0
        )
        if _fold_evidence:
            ops = list(ops) + ["folding"]
            record_operation(part, "folding", "inference")

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]
        setup_times_min["folding"] = round(rule["setup_min"], 2)
        run_times_min["folding"] = round((bends * rule["sec_per_bend"] + bend_length_mm * rule["sec_per_mm_bend_length"]) / 60.0, 2)
        # ── WHERE THE FOLD COUNT CAME FROM, ON THE LINE THAT CHARGES IT ──────────────
        #
        # James Gray, 401912-02: "why are we getting this incorrect ever?"
        #
        # We are not, usually — but the sheet cannot say so. When nothing that can SEE the
        # part has counted the bends, the count falls to the SolidWorks model or a drawing
        # note. That fallback is right and the engine has to have it: plenty of parts have
        # their folds only in a callout. What is missing is the sentence saying WHICH, and
        # without it a measured fold and an inferred one look identical on the page — a
        # reader who wants to check has nowhere to start and no reason to suspect they
        # should.
        #
        # 401912-02's own book: "layers not provided so bend vs cut assignment unknown",
        # one Fold row charged at 30 minutes of set-up, and nothing connecting the two.
        # The count was almost certainly right. Nobody could tell.
        #
        # AND THE MESSAGE SAYS ONLY WHAT IS KNOWN. "The export has no BENDLINES" is a
        # claim about a file this run may never have parsed; what is actually true is that
        # THIS RUN DID NOT RECEIVE USABLE LAYER DATA, which has two very different causes —
        # an export written without bend lines, and a hand-off that did not carry the
        # layers through. They need opposite fixes, and a message that picks one sends the
        # reader to the wrong department. So it names both and asks for the file to be
        # checked.
        #
        # `bend_count_source` is already on the record — `_model_measured_zero_bends` reads
        # it to decide whether a zero was measured or merely absent. It has simply never
        # been said out loud.
        # THE MODEL'S NUMBER, WHERE IT DIFFERS FROM THE CHARGE. Never silently: on 401912-02
        # the model carried three bend features and the flat pattern one, and the only way a
        # reader could have known is if somebody opened both files.
        try:
            from fold_count import press_brake_folds as _pf_flag      # noqa: PLC0415
            _fd = _pf_flag(part).get("disagreement")
            if _fd:
                part.setdefault("review_flags", []).append(_fd)
        except Exception:                                             # noqa: BLE001
            pass
        _bsrc = str((part.get("manufacturing_features") or {}).get(
            "bend_count_source") or "").strip()
        if _bsrc.lower() in _MEASURED_BEND_SOURCES:
            part.setdefault("review_flags", []).append(
                f"{bends:g} fold(s) charged, counted by {_bsrc} — measured, not inferred.")
        else:
            _ng_fold = part.get("normalized_geometry") or {}
            _layers_seen = bool(_ng_fold.get("layers") or part.get("dxf_layers"))
            part.setdefault("review_flags", []).append(
                f"{bends:g} fold(s) charged, and NOTHING THAT CAN SEE THE PART COUNTED "
                f"THEM" + (f" — the count came from {_bsrc}" if _bsrc else "")
                + ". "
                + ("THIS RUN DID NOT RECEIVE USABLE DXF LAYER DATA, so the fold rests on "
                   "the drawing note or the model rather than on bend-line evidence. Two "
                   "things cause that and they need opposite fixes: the flat may have been "
                   "exported without bend lines, or the layers may not have reached the "
                   "route reader. Check whether the staged flat carries a BENDLINES layer, "
                   "and confirm the count meanwhile."
                   if not _layers_seen else
                   "Layers were read and none of them named bend lines. Confirm the count "
                   "against the drawing."))

    # THE COAT IS CHARGED ON EVIDENCE, NOT ON CLASS. The first cut of this gate shed the
    # op from every bought-in and every area-less parent, and the reviewer's probes
    # broke both: a purchased UNFINISHED component can genuinely need coating, and a
    # welded assembly can be coated after assembly. So: a bought-in sheds the op only
    # when NO finish evidence of its own stands behind it (the blanket document stamp
    # no longer reaches bought-ins, so an op that remains is claimed by something); and
    # a parent with no measurable area of its own keeps the op but charges nothing —
    # missing area is a question for a person, never a min-floor charge and never proof
    # that the members already pay.
    _pc_roles = {str(r).lower() for r in (part.get("page_roles") or [])}
    _pc_bought = ("bought_in" in _pc_roles or bool(part.get("bought_in"))
                  or str(part.get("normalized_material") or "").upper() == "BOUGHT_IN")
    _pc_parent = bool(part.get("is_assembly_parent") or part.get("is_sub_assembly"))
    _pc_own_evidence = bool(part.get("surface_finishes")) or any(
        "coat" in str(o).lower() or "powder" in str(o).lower()
        for o in (part.get("textual_operations") or []))
    if "powder_coating" in ops and _pc_bought and not _pc_own_evidence:
        ops = [o for o in ops if o != "powder_coating"]
        part.setdefault("review_flags", []).append(
            "powder coat not charged on this line: a purchased item with no finish "
            "evidence of its own arrives finished")
    if "powder_coating" in ops:
        pc_rule = LABOUR_RULES["powder_coating"]
        setup_pm = float(pc_rule.get("setup_min_per_part", pc_rule.get("min_per_part", 0.75)))
        throughput = float(pc_rule.get("throughput_m2_per_hour", 15.0))
        _reliable_m2 = part.get("_powder_reliable_coated_m2")
        if _reliable_m2 is not None and float(_reliable_m2) > 0:
            coated_m2 = float(_reliable_m2)
            coated_detail = {"coated_area_source": "powder_consumable_reliable_blank"}
        else:
            # No reliable blank => powder material was suppressed. Do NOT invent an
            # inflated area from drawing-extent dims; floor to nominal handling + flag.
            coated_m2 = 0.0
            coated_detail = {"coated_area_source": "no_reliable_blank_floored", "powder_labour_floored": True}
        run_min = 0.0
        if throughput > 0 and coated_m2 > 0:
            run_min = (coated_m2 / throughput) * 60.0
        # The elevated wire/formed powder floor (extra manual hanging/handling time) applies
        # only to genuinely wire-formed parts that have NO flat sheet blank. A flat sheet part
        # that merely carries a weld (e.g. welded footbase 3886-02) coats like sheet and must
        # use the normal floor — the 3-min wire floor is what produced the £17.82 phantom.
        _has_flat_blank = bool(blank_length_pm and blank_width_pm)
        _wire_pc_floor = float(pc_rule.get("wire_min_run_min", 3.0))
        _normal_pc_floor = float(pc_rule.get("min_run_min", 0.25))
        _pc_min = _wire_pc_floor if (_is_wire_op_part and not _has_flat_blank) else _normal_pc_floor
        run_min = max(_pc_min, run_min)
        if _pc_parent and coated_m2 <= 0:
            # AN ASSEMBLY CLAIMING THE COAT WITH NO AREA OF ITS OWN IS A QUESTION, NOT A
            # CHARGE. 11350-01 min-floored both parents on top of the members — the same
            # coat priced twice — but a welded assembly genuinely coated after assembly
            # is real too, and the engine cannot tell those apart from here. So nothing
            # is charged on the parent's line, the claim stays visible on the route, and
            # the flag asks a person to rule on the scope.
            run_min = 0.0
            setup_pm = 0.0
            coated_detail["powder_scope_question"] = True
            part.setdefault("review_flags", []).append(
                "powder is claimed on this assembly and it has no measurable coated area "
                "of its own — the members' areas carry the coat unless a person rules "
                "that the assembly is coated as one; nothing is charged on this line "
                "meanwhile")
        setup_times_min["powder_coating"] = round(setup_pm, 2)
        run_times_min["powder_coating"] = round(run_min, 2)
        powder_coating_detail = {
            "coated_m2": round(coated_m2, 4),
            "throughput_m2_per_hour": throughput,
            "setup_min_per_part": round(setup_pm, 2),
            "run_min_per_unit": round(run_min, 2),
            "hourly_rate_note_gbp": "P/C → powder_coating; SPRY → wet_spray via HOURLY_RATES_GBP / labour_rates",
            **coated_detail,
        }

    if "wet_spray" in ops:
        ws_rule = LABOUR_RULES.get("wet_spray") or {}
        setup_pm = float(ws_rule.get("setup_min_per_part", 0.75))
        throughput = float(ws_rule.get("throughput_m2_per_hour", 22.0))
        coated_m2, coated_detail_ws = _powder_coated_area_m2(part, blank_length_pm, blank_width_pm)
        run_min = 0.0
        if throughput > 0 and coated_m2 > 0:
            run_min = (coated_m2 / throughput) * 60.0
        run_min = max(float(ws_rule.get("min_run_min", 0.25)), run_min)
        setup_times_min["wet_spray"] = round(setup_pm, 2)
        run_times_min["wet_spray"] = round(run_min, 2)
        if powder_coating_detail is None:
            powder_coating_detail = {
                "coated_m2": round(coated_m2, 4),
                "throughput_m2_per_hour": throughput,
                "setup_min_per_part": round(setup_pm, 2),
                "run_min_per_unit": round(run_min, 2),
                "hourly_rate_note_gbp": "wet_spray booth labour (area model shared with powder costing)",
                **coated_detail_ws,
            }

    if "cnc" in ops:
        cnc_rule = LABOUR_RULES.get("cnc") or {}
        setup_times_min["cnc"] = round(float(cnc_rule.get("setup_min", 4.0)), 2)
        sec_per_mm = float(cnc_rule.get("sec_per_mm_contour", 0.04))
        run_sec = max(float(cnc_rule.get("min_run_min", 1.0)) * 60.0, cut_length_mm * sec_per_mm)
        run_times_min["cnc"] = round(run_sec / 60.0, 2)

    if "cnc_routing" in ops:
        cnc_rule = LABOUR_RULES.get("cnc_routing") or LABOUR_RULES.get("cnc") or {}
        setup_times_min["cnc_routing"] = round(float(cnc_rule.get("setup_min", 4.0)), 2)
        sec_per_mm = float(cnc_rule.get("sec_per_mm_contour", 0.04))
        run_sec = max(float(cnc_rule.get("min_run_min", 8.0)) * 60.0, cut_length_mm * sec_per_mm)
        run_times_min["cnc_routing"] = round(run_sec / 60.0, 2)

    if "edge_banding" in ops:
        eb_rule = LABOUR_RULES.get("edge_banding") or {}
        setup_times_min["edge_banding"] = round(float(eb_rule.get("setup_min", 3.0)), 2)
        # THE EDGES THAT ARE BANDED, NOT THE FOUR THAT EXIST.
        #
        # D-104 outlawed the perimeter as the banded LENGTH and this line — the labour
        # beside it, timing the same work — kept using 2*(L+W). On Tony's tray that is
        # 1.56 m a part against his 5 m for the whole assembly: the material was fixed and
        # the minutes went on being charged against a length nobody bands.
        #
        # Same order of trust as the material: a confirmed extent first, then whatever the
        # drawing marks, and the perimeter only where the drawing SAYS all round. Where
        # nothing establishes a length the perimeter is still used — the bander is running,
        # the work is real, and a floor is better than nothing — but it is flagged as the
        # ceiling it is rather than presented as a measurement.
        try:
            from edge_banding import banded_length_mm as _eb_banded
            _eb = _eb_banded(part) or {}
        except Exception:                                            # noqa: BLE001
            _eb = {}
        edge_mm = _safe_float(_eb.get("mm")) or 0.0
        if edge_mm <= 0:
            edge_mm = 2.0 * ((blank_length_pm or 0.0) + (blank_width_pm or 0.0))
            if edge_mm > 0:
                part.setdefault("review_flags", []).append(
                    f"EDGE BANDING TIMED ON THE PERIMETER ({edge_mm:g} mm): nothing on this "
                    f"part says which edges are banded, so the time is a CEILING and not a "
                    f"measurement. Mark the banded edges on the drawing, or confirm the "
                    f"metres, and the minutes follow the length.")
        else:
            part.setdefault("review_flags", []).append(
                f"Edge banding timed on {edge_mm / 1000.0:g} m of banded edge "
                f"({_eb.get('basis')}) — not the perimeter.")
        sec_per_mm = float(eb_rule.get("sec_per_mm_edge", 0.08))
        run_sec = max(float(eb_rule.get("min_run_min", 4.0)) * 60.0, edge_mm * sec_per_mm)
        run_times_min["edge_banding"] = round(run_sec / 60.0, 2)

    if "bench_work" in ops:
        bw = LABOUR_RULES.get("bench_work") or {}
        run_times_min["bench_work"] = round(float(bw.get("min_per_part", 2.0)), 2)

    if "diamond_polish" in ops:
        setup_times_min["diamond_polish"] = 0.5
        run_times_min["diamond_polish"] = round(max(1.0, (cut_length_mm / 500.0)) if cut_length_mm else 1.5, 2)

    if "glue" in ops:
        # WHO DOES THE BONDING, AND HOW LONG THE BOOK SAYS IT TAKES. One decision, in the
        # one place glue minutes are set, because this op has been wrong at both ends.
        #
        # NOT ON AN ARRANGEMENT. 12349-02's GA record charged "Glue — 6mm TIMBER
        # (12349-02-69)" off the word GLUE in the arrangement drawing's notes, and the
        # estimator's question was "What op is this for?" — unanswerable, because an
        # arrangement's notes describe its MEMBERS, and the members already carry their own
        # bonding. A node whose children include another assembly is stamped
        # is_arrangement_parent upstream (drawing_job_merge).
        #
        # AND ON A BONDED ACRYLIC ASSEMBLY, FROM THE ACRYLIC BOOK. "Why is operation for
        # glue 12349-02-69-01A only showing 1 minute (where did this time come from)" — the
        # same estimator, about the generic default below. ACRYLIC_OP_DRIVERS carries SDI's
        # own figure, reverse-engineered from the M18 workbook: 2.4 min per bonded assembly
        # on a 30-minute set-up, and its note says glue and flame-polish are "ONE op per
        # bonded/display assembly, not per panel". The block that applies it lives in
        # estimate_part behind `not is_assembly_parent` — so the only kind of part the
        # driver exists for is the one kind it never reached, and 01A, seven bonded panels,
        # took the flat minute. That gate stays where it is: it keeps laser, linebend and
        # the rest of the geometry route off a parent that cuts nothing.
        _glue_mat = str(part.get("normalized_material") or "").upper().replace("_", " ")
        _glue_drv = getattr(config, "ACRYLIC_OP_DRIVERS", {}) or {}
        _glue_assembly = bool(part.get("is_assembly_parent") or part.get("is_sub_assembly"))
        _glue_acrylic_assembly = (
            _glue_assembly
            and _glue_mat in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA",
                              "POLYCARBONATE"}
            and float(_glue_drv.get("glue_min_per_assembly", 0) or 0) > 0)

        if part.get("is_arrangement_parent"):
            part.setdefault("review_flags", []).append(
                "glue note on the arrangement drawing NOT charged here — the gluing it "
                "calls up belongs to the members, which carry their own bonding time")
        elif _glue_acrylic_assembly:
            setup_times_min["glue"] = float(_glue_drv.get("glue_setup_min", 30.0))
            run_times_min["glue"] = round(float(_glue_drv["glue_min_per_assembly"]), 4)
            part.setdefault("review_flags", []).append(
                f"bonded acrylic assembly: glue timed from the SDI acrylic model "
                f"({run_times_min['glue']:g} min per assembly, set-up "
                f"{setup_times_min['glue']:g} min), not the generic default")
        else:
            setup_times_min["glue"] = 0.5
            run_times_min["glue"] = 1.0

    if "dress_welds" in ops:
        setup_times_min["dress_welds"] = 0.5
        # DRESSING FOLLOWS THE WELD, INCLUDING WHEN THE WELD IS AN ALLOWANCE. 0.5 min is
        # Tim's "Dress (Minimal)" on 12120 — a single short bead. On a whole weldment the
        # welding department says 20 minutes, and a sheet that books 30 minutes of welding
        # beside 1 minute of dressing is not describing the same part twice.
        # Asked here rather than read off a flag: dressing is timed BEFORE welding in this
        # function, so the flag the weld branch sets does not exist yet. One predicate, two
        # readers — a copy that could drift is how 30 minutes of welding ended up beside one
        # minute of dressing in the first place.
        _dm = getattr(config, "WELD_TIME_MODEL", {}) or {}
        _d_mm, _d_joints = _weld_geometry(part)
        _d_weldment = is_weldment_parent(part)
        if _weld_time_is_an_allowance(part, ops):
            run_times_min["dress_welds"] = round(
                float(_dm.get("dress_allowance_min_per_weldment", 20.0)), 2)
            part.setdefault("review_flags", []).append(
                f"dressing follows the weld allowance: {run_times_min['dress_welds']:g} min "
                f"per weldment — {_dm.get('allowance_source', 'shop figure')}")
        elif _d_weldment and _d_joints > 0 and _d_mm <= 0 and "welding" in (ops or ()):
            # Scaled with the weld it follows. A sheet that books welding per joint and
            # dressing per bead is describing two different parts.
            run_times_min["dress_welds"] = round(
                _d_joints * float(_dm.get("dress_min_per_joint", 6.7)), 2)
            part.setdefault("review_flags", []).append(
                f"dressing timed per joint: {_d_joints} joint(s) at "
                f"{_dm.get('dress_min_per_joint', 6.7):g} min, following the weld")
        elif _d_weldment and _d_mm > 0 and "welding" in (ops or ()):
            # THE THIRD BRANCH, WHICH WAS THE 0.5-MINUTE HOLE. A pack that states a weld
            # LENGTH sends welding to the arc-time model and left dressing on Tim's minimal
            # single-bead figure — so the better the drawing, the more absurd the pair: a
            # metre of weld beside thirty seconds of linishing.
            #
            # Dressing is a fixed fraction of welding in both of the shop's own statements —
            # 20 against 30 on the weldment, 6.7 against 10 a joint, 0.67 either way — so the
            # length branch uses the same fraction rather than a fourth number nobody gave us.
            _speed_d = float(_dm.get("travel_speed_mm_per_min", 300.0)) or 300.0
            _of_d = float(_dm.get("operating_factor", 0.35)) or 0.35
            _weld_min_d = (_d_mm / _speed_d) / _of_d + _d_joints * float(
                _dm.get("handling_min_per_joint", 2.0))
            _ratio_d = (float(_dm.get("dress_min_per_joint", 6.7))
                        / max(1e-9, float(_dm.get("weld_min_per_joint", 10.0))))
            run_times_min["dress_welds"] = round(max(0.5, _weld_min_d * _ratio_d), 2)
            part.setdefault("review_flags", []).append(
                f"dressing scaled to the weld: {_weld_min_d:.1f} min of welding on "
                f"{_d_mm:g} mm × {_ratio_d:.0%} — the shop's own dress-to-weld ratio, "
                f"because the pack states a length but no dressing time")
        else:
            # Tim's 12120 "Dress (Minimal)" = 120/hr = 0.5 min/unit (config lever).
            run_times_min["dress_welds"] = float(
                getattr(config, "DRESS_WELD_RUN_MINUTES", 0.5))

    if "handling" in ops:
        run_times_min["handling"] = round(LABOUR_RULES["handling"]["min_per_part"], 2)
        # A PART THAT LEAVES THE BUILDING IS PACKED TWICE.
        #
        # "There would be consideration for two ops for Packing — to and from Plater & Final
        # Assembly / Pack. Manual Estimate for 4 Minutes Pack for Platers / 8 Minutes Final
        # Assembly & Pack." The sheet booked one pack of 2 minutes for both. The second pack
        # is not the first one again: the part goes out raw, comes back plated, and is then
        # assembled and packed for the customer.
        #
        # Keyed on the part's own finish naming a plating family, so a job with no plated
        # part reaches none of it.
        # A NAMED SPEC IS ITSELF EVIDENCE OF PLATING. finish_families reads the process words
        # — PLATED, ZINC — and "Harrods01" is neither: it is the customer's name for a brass
        # plate, which is exactly why the spec table exists. A finish that names a spec in
        # that table goes to a plater by definition, so it counts here too. Without this the
        # part whose plating costs £— was the one part not recognised as plated.
        # TWO OPERATIONS, TWO ROWS — his answer to "say if you would rather see them
        # split": "Two separate Operations this job, items need to be packed to send to
        # platers before" the final pack. One combined 12-minute figure was the right
        # money and the wrong record: neither 4 nor 8 could be checked against it, and
        # the route did not say the part leaves the building in the middle. So the pack
        # to the plater is its own operation (`plater_pack`, PACM department, its own
        # row) and `handling` keeps the final assembly & pack.
        _fin_txt = _part_finish_text(part)
        if _is_plate_finish(_fin_txt) or named_plate_spec(_fin_txt):
            _pl = getattr(config, "PLATING_LOGISTICS", {}) or {}
            _to_plater = float(_pl.get("pack_for_plater_min", 4.0))
            _final = float(_pl.get("final_pack_min", 8.0))
            if _to_plater > 0 and "plater_pack" not in ops:
                ops = list(ops) + ["plater_pack"]
                record_operation(part, "plater_pack", "override_rule")
                run_times_min["plater_pack"] = round(_to_plater, 2)
            if _final > 0:
                # ITS OWN OPERATION, FOR THE REASON THE PACK-OUT ALREADY HAS ONE.
                #
                # This wrote over run_times_min["handling"] — the department's general
                # allowance, which every other part on the job also writes. The workbook
                # emits one row per department, so the plated part's stated 8 minutes was
                # pooled with everybody else's generic 2 and the row came out at 30/hr,
                # which IS 2 minutes a unit. The stated figure had been computed correctly
                # and then averaged away, one link further down than the last four times.
                #
                # So the pack BACK is its own operation, exactly as the pack OUT is: its
                # own key, its own PACM row, its own stated time that nothing can dilute.
                # The part's generic handling allowance comes off, because the two occasions
                # Howard described ARE the handling on a plated part — leaving it would
                # charge a third pack nobody does.
                if "plater_final_pack" not in ops:
                    ops = list(ops) + ["plater_final_pack"]
                    record_operation(part, "plater_final_pack", "override_rule")
                run_times_min["plater_final_pack"] = round(_final, 2)
                ops = [o for o in ops if str(o).strip().lower() != "handling"]
                run_times_min.pop("handling", None)
                setup_times_min.pop("handling", None)
            if _to_plater + _final > 0:
                part["plater_pack_applied"] = True
                part.setdefault("review_flags", []).append(
                    f"plated part: packed TWICE, as two operations on two rows — "
                    f"{_to_plater:g} min a unit pack to the plater and {_final:g} min a "
                    f"unit final assembly and pack, in place of the single "
                    f"{LABOUR_RULES['handling']['min_per_part']:g} min handling allowance "
                    f"({_pl.get('source', 'shop figure')}). Split per the estimator: 'Two "
                    f"separate Operations this job'. NOTE: each row takes the template's "
                    f"own PACM set-up, so the split books TWO set-ups — one per occasion "
                    f"(packing out, and packing back after plating). If the bench regards "
                    f"these as one set-up, say so and the second comes off")

    if "wire_forming" in ops:
        _wire_len_mm = _safe_float(part.get("wire_total_length_mm")) or cut_length_mm
        setup_times_min["wire_forming"] = 5.0
        run_times_min["wire_forming"] = round(
            max(1.0, (_wire_len_mm / 500.0) if _wire_len_mm else 1.0), 2
        )

    if "welding" in ops:
        # A WELD ASSEMBLY HAS NO FLAT, AND BOTH DRIVERS HERE ARE PROPERTIES OF ONE.
        # pierces and cut_length_mm describe a blank; a weldment is what blanks become, so
        # both read zero on the only kind of part welding runs on and the time took the
        # 1-minute floor. 7332-01 booked 2 minutes where the welding department says 30.
        # See config.WELD_TIME_MODEL for the method, the sources, and whose number the
        # allowance is.
        _wm = getattr(config, "WELD_TIME_MODEL", {}) or {}
        setup_times_min["welding"] = float(_wm.get("setup_min_per_weldment", 3.0))
        _weld_mm, _joints = _weld_geometry(part)
        # THE SECOND COPY OF THE TEST, AND THE ONE THAT HELD THE MONEY. Dressing read the
        # same two booleans through _weld_time_is_an_allowance and welding read them here
        # directly, so widening one left a sheet booking 20 minutes of dressing beside one
        # minute of welding — the exact shape the predicate above exists to prevent, in the
        # other direction. One reader now, for both.
        _is_weldment = is_weldment_parent(part)

        if _weld_mm > 0:
            # The published model, the moment a pack states a weld LENGTH.
            _speed = float(_wm.get("travel_speed_mm_per_min", 300.0)) or 300.0
            _of = float(_wm.get("operating_factor", 0.35)) or 0.35
            _arc = (_weld_mm / _speed) / _of
            _handle = _joints * float(_wm.get("handling_min_per_joint", 2.0))
            run_times_min["welding"] = round(max(1.0, _arc + _handle), 2)
            part.setdefault("review_flags", []).append(
                f"weld timed from geometry: {_weld_mm:g} mm of weld at "
                f"{_speed:g} mm/min and {_of:.0%} operating factor"
                + (f", plus {_joints} joint(s) handling" if _joints else ""))
        elif _joints > 0:
            # No length, but the joints can be counted — so the time scales with the work.
            # This is what keeps a four-member frame's 30 minutes off a two-part holder.
            run_times_min["welding"] = round(
                max(1.0, _joints * float(_wm.get("weld_min_per_joint", 10.0))), 2)
            part["weld_time_is_per_joint"] = _joints
            part.setdefault("review_flags", []).append(
                f"weld timed per joint: {_joints} joint(s) at "
                f"{_wm.get('weld_min_per_joint', 10.0):g} min — the pack states no weld "
                f"length, so the joints are counted from the {_joints + 1} members this "
                f"weldment joins. Rate from {_wm.get('allowance_source', 'the shop')}")
        elif _is_weldment:
            # No weld length and no joint count anywhere in the pack. Rather than a floor
            # that reads as a measurement, the shop's own stated allowance, labelled.
            run_times_min["welding"] = round(
                float(_wm.get("allowance_min_per_weldment", 30.0)), 2)
            part["weld_time_is_an_allowance"] = True
            part.setdefault("review_flags", []).append(
                f"WELD TIME IS AN ALLOWANCE, not a measurement: the pack states no weld "
                f"length or joint count, so this carries "
                f"{run_times_min['welding']:g} min per weldment — "
                f"{_wm.get('allowance_source', 'shop figure')}. Supply a weld length or a "
                f"joint count on the drawing and it is computed instead")
        else:
            run_times_min["welding"] = round(
                max(1.0, (pierces * 90.0 + cut_length_mm * 0.01) / 60.0), 2)

    if "resistance_welding" in ops or "spot_welding" in ops:
        _weld_key = "resistance_welding" if "resistance_welding" in ops else "spot_welding"
        setup_times_min[_weld_key] = 2.0
        run_times_min[_weld_key] = round(max(0.5, (pierces * 45.0) / 60.0), 2)

    if "deburring" in ops:
        setup_times_min["deburring"] = 1.0
        run_times_min["deburring"] = round(max(0.5, (pierces * 30.0) / 60.0), 2)

    # ── TIMBER / BOARD process allowance (no-geometry) ──────────────────────────────────
    # A wood/board part on a PDF gives a printed WEIGHT but no blank L×W, so every geometry-based
    # timer above reads 0 and the panel gets ZERO labour — yet a sawn, rebated, glued-and-pinned,
    # lacquered timber panel plainly has labour content. When no cutting op fired and there is no
    # cut length, assign flat per-part ALLOWANCES at the REAL shop rates (SAW/CNC-rout/GLUE/SPRY/
    # assembly) so labour is a sensible, FLAGGED figure the estimator refines — never £0, never a
    # metal-laser lie. Minutes are config-tunable (TIMBER_LABOUR_ALLOWANCE_MIN). Geometry-backed
    # timber (from a DXF) keeps its real timing and skips this.
    _mat_family = _mat_u.replace(" ", "_")
    _TIMBER_FAMILIES = {"TIMBER", "WOOD", "MDF", "MDF_BOARD", "VENEERED_MDF", "OAK_VENEER_MDF",
                        "PLYWOOD", "BIRCH_PLYWOOD", "SOFTWOOD", "HARDWOOD", "PINE"}
    # Fire for ANY no-DXF timber/board part. We deliberately do NOT gate on cut_length: a PDF
    # vector rollup often yields a phantom cut length, which previously (a) skipped this whole
    # allowance and (b) let a metal 'laser_cutting' op attach to timber. A timber panel is sawn/
    # routed, never metal-lasered, so we STRIP any inferred laser and assign the joinery route.
    # Real DXF-backed timber keeps its measured timing and skips this.
    _timber_dxf = ("dxf" in str(part.get("geometry_source") or "").lower()
                   or bool(part.get("dxf_augmented")) or bool(part.get("flat_pattern_detected")))
    # A tube / section / wire / bar is a bought steel section — SDI saws-to-length, bends and
    # welds it; it is NEVER joinery-routed (saw+CNC-rout+glue+wet-spray). When such a part is
    # mis-tagged as a timber family (e.g. a steel FRONT POST CROSS RAIL that the boilerplate
    # scan called TIMBER), the timber allowance below would bolt a full joinery route onto it
    # and blow the labour up. Gate the allowance off for section-form parts, whatever the
    # material tag says — its real route (weld/handling) comes from the tube path. General.
    _stock_form_now = str((part.get("material_estimate") or {}).get("stock_form")
                          or (part.get("manufacturing_interpretation") or {}).get("stock_form")
                          or "").lower()
    _section_like = (
        _stock_form_now in ("tube", "wire", "section", "bar")
        or _is_section_or_wire_candidate(part, part.get("normalized_material"))
    )
    if (_mat_family in _TIMBER_FAMILIES and not _timber_dxf and not _section_like
            and not part.get("is_assembly_parent")
            and not any(o in ("saw", "cnc_routing", "cnc") for o in set(run_times_min))):
        # Timber is not laser-cut — drop any metal laser op the sheet/board inference attached.
        for _bad in ("laser_cutting", "guillotine", "punch"):
            run_times_min.pop(_bad, None)
            setup_times_min.pop(_bad, None)
        _alloc = getattr(config, "TIMBER_LABOUR_ALLOWANCE_MIN", None) or {
            "saw": 1.5, "cnc_routing": 2.0, "glue": 1.5, "wet_spray": 1.5, "handling": 1.0,
        }
        for _top, _mins in _alloc.items():
            _m = float(_mins or 0.0)
            if _m <= 0:
                continue
            run_times_min[_top] = round(run_times_min.get(_top, 0.0) + _m, 2)
            setup_times_min.setdefault(_top, 1.0)
        part["timber_labour_allowance"] = True
        part.setdefault("review_flags", []).append(
            "timber labour is a FLAT PER-PART ALLOWANCE (saw/rout/glue/lacquer at shop rates) — "
            "no panel dimensions on the PDF to time it precisely; estimator to refine")

    # Special / bought-in finishing items (tiles, mosaics, graphics, vinyl, -X suffix) carry
    # NO fabrication labour, whatever the inference or timber-allowance blocks above added —
    # they are bought in, not made. Final strip so only handling/assembly survives.
    if part.get("special_finish_item"):
        for _timing in (setup_times_min, run_times_min):
            for _op in list(_timing.keys()):
                if _op in _SPECIAL_ITEM_FAB_OPS:
                    _timing.pop(_op, None)

    unit_times_min: Dict[str, float] = {}
    total_times_min: Dict[str, float] = {}
    for op in set(setup_times_min) | set(run_times_min):
        unit_times_min[op] = round(setup_times_min.get(op, 0.0) + run_times_min.get(op, 0.0), 2)
        total_times_min[op] = round(setup_times_min.get(op, 0.0) + (run_times_min.get(op, 0.0) * quantity), 2)

    return {
        "cut_length_mm": round(cut_length_mm, 2),
        "raw_cut_length_mm": round(raw_cut_length_mm, 2),
        "pierce_count": pierces,
        "hole_count": holes,
        "bend_count": bends,
        "bend_length_mm": round(bend_length_mm, 2),
        "setup_times_min": setup_times_min,
        "run_times_min_per_unit": run_times_min,
        "unit_times_min": unit_times_min,
        "times_min": total_times_min,
        "unit_time_min": round(sum(unit_times_min.values()), 2),
        "total_time_min": round(sum(total_times_min.values()), 2),
        "feature_rollup": part.get("feature_rollup", {}),
        "manufacturing_features": manufacturing_features,
        "routing": part.get("manufacturing_interpretation", {}).get("routing", []),
        "geometry_reliability": geometry_confidence,
        "powder_coating_detail": powder_coating_detail,
    }


def estimate_labour_costs(process: Dict[str, Any], job_quantity: int = 1, material: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute per-unit labour cost matching the workbook M63 formula exactly:

        M = H + (rate/60 × setup_mins) / D6

    Where H = run_cost_per_unit = rate × run_hours_per_unit
    And the setup cost is amortised across the job quantity (D6).

    The workbook's J63 (total batch hours) is also computed for reference:
        J = run_hours_per_unit × job_qty + setup_mins/60
    """
    breakdown: Dict[str, float] = {}
    setup_amortised: Dict[str, float] = {}
    run_costs: Dict[str, float] = {}
    batch_hours: Dict[str, float] = {}
    run_hours_per_unit: Dict[str, float] = {}
    rate_sources: Dict[str, Any] = {}
    missing_rate_operations: List[str] = []

    setup_times = process.get("setup_times_min", {})
    run_times = process.get("run_times_min_per_unit", {})
    all_ops = set(setup_times) | set(run_times)
    qty = max(1, int(job_quantity))

    _mat_u = str(material or "").upper()
    _ACRYLIC_LIKE = {"ACRYLIC", "POLYCARBONATE", "PETG", "HIPS", "HDPE_PLASTIC", "FOAMEX"}
    for op in all_ops:
        external_rate = _resolve_labour_rate(op)
        applied_hourly_rate = external_rate.get("applied_hourly_rate")
        # Material-aware rate key: acrylic/plastic laser cutting + assembly use
        # the cheaper non-metal rates (laser_cutting_acrylic, assembly_acrylic).
        _rate_key = op
        # acrylic_rate_key_override (2026-07-15): for an acrylic part, an acrylic op must be
        # priced at its ACRYLIC department rate (MANA/LASA/PACP/DPOL from the rate card), NOT
        # the metal department. The pricing resolver returns the METAL manual rate (MANM
        # £31.18) for manual_labour, and that was winning over the correct MANA £25.43 — the
        # Peel line came out 23% over. This picks the authoritative acrylic rate from
        # HOURLY_RATES_GBP and OVERRIDES the resolved metal rate for acrylic parts.
        _acr_rate = None
        if _mat_u in _ACRYLIC_LIKE:
            # existing laser/assembly remaps (kept), now also actually applied via _acr_rate
            if op == "laser_cutting" and "laser_cutting_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "laser_cutting_acrylic"
            elif op == "assembly" and "assembly_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "assembly_acrylic"
            # general: the op's own explicit "<op>_acrylic" variant, or the op name if it is
            # already an acrylic-specific key (manual_labour_acrylic, diamond_polish, linebend).
            for _cand in (f"{op}_acrylic", _rate_key, op):
                if _cand in HOURLY_RATES_GBP:
                    _acr_rate = HOURLY_RATES_GBP[_cand]
                    _rate_key = _cand
                    break
        if _acr_rate is not None:
            rate = _acr_rate   # authoritative acrylic dept rate wins for acrylic parts
        else:
            rate = applied_hourly_rate if applied_hourly_rate is not None else HOURLY_RATES_GBP.get(_rate_key)
        if rate is None:
            run_min = run_times.get(op, 0.0)
            setup_min = setup_times.get(op, 0.0)
            if run_min or setup_min:
                missing_rate_operations.append(op)
            continue

        run_min = float(run_times.get(op, 0.0))
        setup_min = float(setup_times.get(op, 0.0))

        run_cost_unit = rate * (run_min / 60.0)
        setup_cost_unit = (rate / 60.0 * setup_min) / qty
        unit_cost = run_cost_unit + setup_cost_unit

        run_hours_unit = run_min / 60.0
        j_batch_hours = run_hours_unit * qty + (setup_min / 60.0)

        breakdown[op] = round(unit_cost, 4)
        run_costs[op] = round(run_cost_unit, 4)
        setup_amortised[op] = round(setup_cost_unit, 4)
        batch_hours[op] = round(j_batch_hours, 4)
        # A THROUGHPUT IS PIECES PER HOUR AND CANNOT DEPEND ON HOW MANY WERE ORDERED.
        #
        # batch_hours mixes run time with a one-off setup, so anything derived from it
        # inherits the quantity it was built for. wb_populate divided this job's piece count
        # by it and got a rate that scaled with the order: 11350's fold read 65.85/hr at 180
        # off and 7.32/hr at 20 — exactly 65.85 x 20/180, because the batch figure had been
        # built at 180 either way. The floor caught a 9x error; at 90 off it would have been
        # 2x and passed silently.
        #
        # The run time per piece is the rate, and it has no quantity in it at all.
        run_hours_per_unit[op] = round(run_hours_unit, 6)
        rate_sources[op] = _build_price_source_metadata(
            external_rate.get("result", {}),
            fallback_source=f"config_default_labour_rate:{op}",
            applied=applied_hourly_rate is not None,
            applied_basis=external_rate.get("applied_basis") if applied_hourly_rate is not None else "config_fallback_GBP_per_hour",
        ) | {"hourly_rate_gbp": rate}

    return {
        "costs_gbp": {op: round(v, 2) for op, v in breakdown.items()},
        "run_costs_gbp": run_costs,
        "setup_amortised_gbp": setup_amortised,
        "batch_hours": batch_hours,
        "run_hours_per_unit": run_hours_per_unit,
        "total_labour_cost_gbp": round(sum(breakdown.values()), 2),
        "rate_sources": rate_sources,
        "missing_rate_operations": missing_rate_operations,
        "job_quantity_used": qty,
        "workbook_formula": "M = run_cost_per_unit + (rate/60 × setup_mins) / job_qty",
    }


def _sanitise_part_quantity(part: Dict[str, Any]) -> int:
    """
    Guard against the PDF parser reading drawing-number prefixes as quantities.
    e.g. part_number="8172-01_WELDMENT" -> quantity=8172 (WRONG, should be 1).

    Rules:
      1. If quantity matches the leading numeric block of the part number -> reset to 1.
      2. If quantity > MAX_PART_QTY_PER_UNIT (default 50) -> reset to 1.
      Both cases add a review_flag warning to the part.
    """
    raw_qty = _safe_int(part.get("quantity")) or 1
    if raw_qty <= 1:
        return 1

    _MAX = int(getattr(config, "MAX_PART_QTY_PER_UNIT", 50))
    pn = str(part.get("part_number") or "").replace(" ", "")

    _m = re.match(r"^(\d+)", pn)
    if _m and int(_m.group(1)) == raw_qty:
        part.setdefault("review_flags", []).append({
            "severity": "warning",
            "flag": "quantity_from_part_number",
            "detail": f"qty {raw_qty} matched leading digits of part_number '{pn}' — reset to 1",
        })
        return 1

    if raw_qty > _MAX:
        part.setdefault("review_flags", []).append({
            "severity": "warning",
            "flag": "quantity_capped",
            "detail": f"qty {raw_qty} > MAX_PART_QTY_PER_UNIT ({_MAX}) — reset to 1",
        })
        return 1

    return raw_qty


def apply_production_substitutions(part: Dict[str, Any]) -> None:
    """The shop costs the material it actually buys, and says so beside the drawn figure.

    "0.9mm Steel Production use 1mm in Lieu" — raised TBC on 9 Sep, confirmed in Howard
    Thurley's 15 Sep 7332-01 reply. While it was TBC the engine flagged and costed as
    drawn; a confirmed rule costs the substitute, because 0.9 mm steel cannot be bought and
    a price on a gauge the buyer cannot order under-charges the difference on every job.

    THREE STATES, ALL SAID OUT LOUD:
      confirmed rule    the substitute gauge is costed; the drawn figure stays on the part
                        (`drawn_thickness_mm`) and in the flag.
      person overrode   an estimator-confirmed thickness (rank 100) outranks any rule —
                        the answers file simply states thickness_mm — and the substitution
                        stands down, saying it did.
      rule not firm     status other than "confirmed" flags and costs as drawn, exactly as
                        the TBC handling always did.
    """
    _gauge = _safe_float(part.get("normalized_thickness_mm")) or 0.0
    if _gauge <= 0 or part.get("production_substitution"):
        return
    _mat = str(part.get("normalized_material") or "").upper().replace("_", " ")
    for rule in getattr(config, "PRODUCTION_MATERIAL_SUBSTITUTIONS", None) or []:
        if _mat not in tuple(rule.get("materials") or ()):
            continue
        if not (float(rule.get("drawn_mm_low", 0)) <= _gauge
                <= float(rule.get("drawn_mm_high", 0))):
            continue
        _sub = float(rule.get("substitute_mm") or 0)
        _who = f"{rule.get('stated_by')}, {rule.get('stated_on')}"
        if str(rule.get("status") or "").lower() != "confirmed":
            part.setdefault("review_flags", []).append(
                f"drawn at {_gauge:g} mm: production has raised substituting {_sub:g} mm "
                f"in lieu ({_who} — {rule.get('status', 'unconfirmed')}). Costed AS "
                f"DRAWN — confirm which gauge is bought before issue")
            return
        _src = source_precedence.source_of(part, "normalized_thickness_mm")
        if source_precedence.rank(_src) >= source_precedence.rank("estimator_confirmed"):
            part.setdefault("review_flags", []).append(
                f"production substitution ({rule.get('rule_id')}) stood down: the "
                f"{_gauge:g} mm gauge is estimator-confirmed ({_src}), and a person's "
                f"ruling outranks a production rule")
            return
        part["drawn_thickness_mm"] = _gauge
        part["production_substitution"] = {
            "rule_id": rule.get("rule_id"), "drawn_thickness_mm": _gauge,
            "costed_thickness_mm": _sub, "reason": rule.get("reason"),
            "stated_by": rule.get("stated_by"), "stated_on": rule.get("stated_on"),
        }
        # The substitute is what the buyer orders and the laser cuts, so it is what every
        # downstream figure (mass, speed table, the workbook's gauge column) must use —
        # and it must SURVIVE. Written through the resolver as its own source
        # (production_substitution, rank 95): above every reading, so a later DXF or model
        # pass cannot quietly put the drawn gauge back; below a person, so an
        # estimator-confirmed thickness still wins.
        source_precedence.apply_field(
            part, "normalized_thickness_mm", _sub, "production_substitution")
        part.setdefault("review_flags", []).append(
            f"drawn at {_gauge:g} mm, COSTED AT {_sub:g} mm: "
            f"{rule.get('reason')} ({_who}). A production rule, not a reading of the "
            f"drawing — to keep the drawn gauge, confirm thickness_mm {_gauge:g} in the "
            f"answers file and this rule stands down")
        return


def estimate_part(part: Dict[str, Any], job_quantity: Optional[int] = None) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    quantity = _sanitise_part_quantity(part)
    # Sanitisation of the part's OWN quantity (None/0/negative -> 1), not a new observation,
    # so the source that supplied it stands. Writing it through the resolver would re-stamp a
    # model-supplied quantity as if the estimator had measured it.
    part["quantity"] = quantity   # precedence: direct-write ok — sanitises the part's own value

    # THE LAST POINT AT WHICH EVERY SOURCE HAS SPOKEN, AND THE FIRST AT WHICH THE PAIR IS
    # SPENT. Material and gauge are resolved as separate fields, so each half can come from a
    # different reading — and 11650-04 landed on PETG at 2.2mm, which the model never said,
    # the export never said, and nobody stocks. Settled HERE rather than inside
    # estimate_material because the gauge drives the laser and the bend as well as the sheet:
    # settling it only where the money is looked up would leave labour costing a thickness
    # that material had already stopped believing in.
    source_precedence.settle_companion_facts(part)

    # AFTER the pair is settled, BEFORE anything reads the gauge: the shop costs the
    # material it actually buys (0.9 mm steel is not stocked; production runs 1.0), and
    # the substitution has to land before the mass, the laser speed and the workbook's
    # gauge column are derived from a thickness the buyer cannot order.
    apply_production_substitutions(part)

    # Commercial placeholders (PACKAGING, DELIVERY) are NOT parts to be estimated — they are
    # always-present reminder lines whose real cost is order-specific and lives in the enquiry,
    # not the drawing. They must pass through UNPRICED (£0, estimator-to-price); running them
    # through material/labour/PricingService would assign a spurious handling/web-AI cost and
    # defeat the whole point. Return the stub's £0 intact.
    if part.get("_commercial_placeholder") or str(part.get("source") or "") == "commercial_placeholder":
        # A PLACEHOLDER THAT HAS BEEN PRICED IS NO LONGER UNPRICED. This zeroed the line
        # unconditionally, so a packaging figure the market had just returned was thrown
        # away one function later — built is not wired, inside the branch whose whole job
        # is to keep these lines honest. Where nothing was found it is still a clean zero
        # with an owner.
        _cp = _safe_float(part.get("unit_material_cost_gbp")) or 0.0
        part["material_estimate"] = {
            "unit_material_cost_gbp": _cp, "cost_per_part_gbp": _cp,
            "extended_material_cost_gbp": round(_cp * max(1, int(quantity or 1)), 2),
            "cost_method": ("commercial_line_market_indication" if _cp
                            else "commercial_placeholder_unpriced")}
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_cost_gbp"] = _cp
        part["unit_total_cost_gbp"] = _cp
        # A PRICED PLACEHOLDER CARRIES ITS COST TO THE TOTAL. This was hard-set to 0.0, so a
        # packaging/delivery line that had just been given a house rate (£2.00 / £2.50 a unit)
        # showed £2.00 each and a LINE TOTAL of £0 — priced on the sheet, absent from the money.
        # The comment above says the priced case must survive; this is where it does. An
        # unpriced placeholder (_cp == 0) is still a clean £0, exactly as before.
        part["extended_total_cost_gbp"] = round(_cp * max(1, int(quantity or 1)), 2)
        return part

    # A bought-in line that already carries a price from the deterministic recogniser or
    # the LLM note-scan must KEEP that price — those layers matched it to a genuine SDI
    # historical/catalogue line (e.g. Foam Tape -> "Foam Tape 890x10x1.5mm" @ £0.28).
    # Re-deriving it via the material+labour path produced absurd figures (a £132 foam
    # tape) because these stubs have no real geometry to cost. Respect the upstream price.
    _preset_src = str(part.get("source") or "")
    _preset_unit = part.get("unit_cost_gbp")
    # A LINE THE RECOGNISER SUSPECTS IS A MADE PART UNDER ANOTHER NAME IS PRICED — AND FLAGGED.
    #
    # The recogniser judges an ambiguous fabrication word ('Foot Plate') a POSSIBLE duplicate of
    # a fabricated part already costed on the sheet (it shares 'plate' with a SCREW PLATE). We
    # used to zero it to avoid paying twice — but that judgement is a heuristic and can be wrong
    # (Foot Plate may be a genuine separate part), and a £0 reads as free, which is the error
    # nobody catches. The mandate is a price on every line until catalogues/APIs replace the
    # guesses. So the line is PRICED through the normal chain below (catalogue / UDEF / market /
    # LLM) and carries a LOUD possible-double-count flag: the estimator sees the number AND the
    # warning, and strikes it if it duplicates a made part. Non-firm, like every market figure.
    if part.get("cost_source") == "layer2_possible_fabricated_query":
        part.setdefault("review_flags", []).append(
            "POSSIBLE DOUBLE-COUNT — this line may be the same part as a fabricated item already "
            "costed on the sheet (a plate/bracket read twice under two names). A market price is "
            "shown so it is not read as free; CONFIRM it is a genuine bought-in and STRIKE it if "
            "it duplicates a made part. Non-firm.")
        # fall through to normal costing so the line carries a price, not a blank.
    # SDI BOM-code stubs (FIXING/VINYL priced from UDEF, or flagged unpriced) must also keep
    # their upstream state — a genuine catalogue price, or an honest "estimator to price".
    if _preset_src == "sdi_bom_code_unpriced":
        # RECOGNISED BUT UNPRICED IS NOT THE SAME AS UNPRICEABLE.
        #
        # This branch returns £0/None for a bought-in the recogniser flagged for pricing — a
        # code the catalogue could not match. But a GENERICALLY-NAMED STANDARD COMMODITY (a
        # pallet, a perforated-panel clip) has a fixed config figure keyed on its description,
        # and this stub short-circuits estimate_part BEFORE _resolve_part_system_cost, so the
        # commodity table there is never reached and the line shipped as £0 — a bought-in
        # reading as free. 11762-17's PERFO PLASTIC LOCKING CLIP is exactly this: 'STD PART'
        # for a code, £1.20 sitting in config, and three runs of £0 because the price lived
        # past the return. Consult the DB-free commodity table here, at the source, so the
        # record itself carries the buy price — no bench-fitting uplift (a standard commodity
        # is placed during the assembly labour the parent already carries), flagged PROVISIONAL.
        _com = None
        try:
            from pricing_service import standard_commodity_price as _std_commodity
            _com = _std_commodity(part)
        except Exception:                                        # noqa: BLE001
            _com = None
        _com_unit = _safe_float(_com.get("unit_price_gbp")) if _com else None
        if _com_unit is not None and _com_unit > 0:
            _com_unit = _round_money(_com_unit)
            _com_ext = _round_money(_com_unit * quantity)
            part["material_estimate"] = {
                "unit_material_cost_gbp": _com_unit, "cost_per_part_gbp": _com_unit,
                "extended_material_cost_gbp": _com_ext,
                "cost_method": "standard_commodity_provisional"}
            part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
            part["unit_cost_gbp"] = _com_unit
            part["unit_total_cost_gbp"] = _com_unit
            part["extended_total_cost_gbp"] = _com_ext
            part["costing_basis"] = "standard_commodity_provisional"
            part["source"] = "standard_commodity_provisional"
            part.setdefault("review_flags", []).append(
                _com.get("review_reason")
                or "Provisional standard-commodity price — confirm against a supplier quote.")
            # SAY IT ON THE CONSOLE. Whether this table fired was only visible by opening the
            # finished workbook and reading one cell — so a run made before a rate was added,
            # and a run where the rate failed to match, looked identical from the outside and
            # cost an evening to tell apart. One line naming the part, the price and where the
            # rate came from answers it while the run is still on screen.
            try:
                print(f"   [pricing] {part.get('part_number') or '?'} "
                      f"({str(part.get('description') or '')[:40]}) priced from the standard "
                      f"commodity table at £{_com_unit:.2f} — "
                      f"{_com.get('price_source_note') or 'source not recorded'}", flush=True)
            except Exception:                                    # noqa: BLE001
                pass
            return part
        # AND THE REST OF THE CHAIN IS PAST THIS RETURN TOO.
        #
        # The commodity table was brought up here because the price lived past the return.
        # It is not the only thing that does: UDEF matched on the line's DESCRIPTION,
        # historical quote lines, the supplier catalogue and the market rung are ALL in
        # _resolve_part_system_cost, and this branch returns before any of them. So the two
        # lines an estimator can price in his sleep — 12349-02's M4 flange button screw and
        # its 3.5x19 wood screw — came back "MATERIAL UNPRICED: enter a unit rate" on run
        # after run, including runs where the catch-all-zero fix had already opened the road,
        # because these lines never travel it. Meanwhile the bumpon on the same bill of
        # materials, which is NOT flagged this way, went down the chain and priced at 35p.
        #
        # Same argument as the commodity table, one rung further out: ask, and take an answer
        # if there is one. A miss changes nothing — the £0/None pass-through below is
        # untouched — so this can only turn a blank into a priced line, never the reverse.
        _chain_unit = None
        try:
            _chain = _resolve_part_system_cost(part)
            _chain_unit = _safe_float(_chain.get("applied_unit_cost"))
        except Exception:                                        # noqa: BLE001
            _chain, _chain_unit = {}, None
        if _chain_unit is not None and _chain_unit > 0:
            _chain_unit = _round_money(_chain_unit)
            _chain_ext = _round_money(_chain_unit * quantity)
            _sel = _extract_selected_price(_chain.get("result") or {})
            _src = str(_sel.get("source") or "price chain")
            part["material_estimate"] = {
                "unit_material_cost_gbp": _chain_unit, "cost_per_part_gbp": _chain_unit,
                "extended_material_cost_gbp": _chain_ext,
                "cost_method": f"bom_code_priced_by_description:{_src}"}
            part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0,
                                       "extended_labour_cost_gbp": 0.0}
            part["unit_cost_gbp"] = _chain_unit
            part["unit_total_cost_gbp"] = _chain_unit
            part["extended_total_cost_gbp"] = _chain_ext
            part["costing_basis"] = f"bom_code_priced_by_description:{_src}"
            if _sel.get("provenance"):
                part["price_provenance_note"] = str(_sel.get("provenance"))
            if _chain.get("matched_part_code"):
                part["matched_part_code"] = _chain["matched_part_code"]
            part.setdefault("review_flags", []).append(
                f"the code column holds a class word, so this line was priced on its "
                f"DESCRIPTION against {_src} — check it is the same item before issue")
            return part

        # THE MISS SAYS IT WAS ASKED. Twice now a class-word line has come back blank on a
        # run whose build contained the fix that should have priced it, and the sheet could
        # not distinguish "the chain was never reached" from "the chain was reached and
        # found nothing" — which are different defects with different fixes, and telling
        # them apart needed the run log. The record answers it now, on its own face.
        _chain_src = ""
        try:
            _chain_sel = _extract_selected_price((_chain or {}).get("result") or {})
            _chain_src = str(_chain_sel.get("source") or _chain_sel.get("reason") or "")
        except Exception:                                        # noqa: BLE001
            _chain_src = ""
        part["price_chain_consulted"] = True
        part.setdefault("review_flags", []).append(
            "the full price chain was asked for this line and returned nothing — catalogue "
            "by code, catalogue by description, historical quotes, supplier list and the "
            "market rung all missed"
            + (f" (last source reached: {_chain_src})" if _chain_src else "")
            + ". If this item is in the buying database, its code or its description does "
              "not match what the sheet carries")

        # Recognised but unpriced — pass through £0/None, flagged, NOT re-costed by geometry.
        part["material_estimate"] = {"unit_material_cost_gbp": None, "cost_per_part_gbp": None,
                                     "extended_material_cost_gbp": None,
                                     "cost_method": "sdi_bom_code_estimator_to_price"}
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_total_cost_gbp"] = None
        part["extended_total_cost_gbp"] = None
        part["costing_basis"] = "sdi_bom_code_estimator_to_price"
        return part
    if (
        (_preset_src in ("prose_recogniser_layer2", "llm_note_scan", "sdi_bom_code_udef_priced")
         or part.get("_layer2_recognised") or part.get("_note_scan"))
        and _preset_unit is not None
    ):
        _bi_unit = _round_money(float(_preset_unit))
        _bi_ext = _round_money(float(_preset_unit) * quantity)
        part["material_estimate"] = {
            "unit_material_cost_gbp": _bi_unit, "cost_per_part_gbp": _bi_unit,
            "extended_material_cost_gbp": _bi_ext,
            "cost_method": f"bought_in_recognised_price:{_preset_src or 'recogniser'}",
        }
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_total_cost_gbp"] = _bi_unit
        part["extended_total_cost_gbp"] = _bi_ext
        part["unit_cost_gbp"] = _bi_unit
        part["costing_basis"] = f"bought_in_recognised_price:{_preset_src or 'recogniser'}"
        return part

    # Machine SETUP amortises over the ORDER (job) quantity, not the per-part
    # qty-per-unit. `quantity` above is qty-per-unit (e.g. 1 peg per bay);
    # `order_qty` is how many units the customer asked us to price. This matches
    # the manual estimate, which spreads setup over the job qty (e.g. 100).
    # Source order: explicit arg -> qty the scan stamped on the part/summary ->
    # config default. Costing setup at qty 1 was the root cause of every part
    # reading 2-10x over the manual.
    order_qty = job_quantity if job_quantity else part.get("assumed_job_quantity")
    order_qty = max(1, int(order_qty or getattr(config, "DEFAULT_JOB_QUANTITY", 180)))
    part["assumed_job_quantity"] = order_qty
    part_number = part.get("part_number") or part.get("item_number") or "unknown_part"
    if debug:
        print(f"[DEBUG] estimate_part start {part_number}")
    # ── GA / overall-unit parent detected by number pattern ────────────────────────
    # A part numbered <job>-00-<xxx> is the top-level unit/GA line (the whole product),
    # not a fabricated leaf. Left as a leaf it double-counts: its stated whole-unit weight
    # becomes a huge material line (Cocktails 12301-00-101 = £389) and it takes a phantom
    # fabrication route. Its children are costed individually, so mark it an assembly parent
    # BEFORE material costing -> material is suppressed (carried by children) and the fab/
    # joinery route is gated off. Guarded on 'no flat pattern of its own', since a genuine
    # fabricated leaf would carry DXF/blank geometry. General, not a Cocktails patch.
    _pn_ga = str(part.get("part_number") or "").upper().strip()
    if (re.match(r"^\d+-0+-\d+$", _pn_ga) and not part.get("flat_pattern_detected")
            and not part.get("is_assembly_parent")):
        part["is_assembly_parent"] = True
        part.setdefault("review_flags", []).append(
            "top-level unit/GA line (…-00-…) treated as assembly parent — material carried "
            "by children, fabrication route suppressed; estimator to verify")
    material = estimate_material(part)
    material = _price_declared_material_layers(part, material)
    if debug:
        print(f"[DEBUG] estimate_part material done {part_number}")
    # FIX 1: feed powder LABOUR area from the SAME reliable blank the powder MATERIAL
    # consumable used, so labour can't diverge from material. None => consumable was
    # suppressed (no reliable blank) => powder labour floors instead of inventing an
    # inflated drawing-extent area (the 3886-02 £17.82 phantom vs its mirror's £1.53).
    try:
        part["_powder_reliable_coated_m2"] = ((material or {}).get("powder_consumable") or {}).get("coated_area_m2")
    except Exception:
        part["_powder_reliable_coated_m2"] = None
    process = estimate_process_times(part, quantity=quantity)
    if debug:
        print(f"[DEBUG] estimate_part process done {part_number}")
    # Assembly/sub-assembly parent: no flat DXF of its own, so it performs no
    # cutting/folding — those are carried by its costed children. Strip the
    # geometry-derived fab ops so it can't bill a phantom laser/fold from the
    # assembly PDF cut-length (TANK 04 read 12.1h laser = £8.26). Genuine assembly
    # ops (weld/glue/assemble/handle/powder) are left intact. CNC is intentionally
    # NOT stripped here — that is a weldment-routing concern handled separately.
    if part.get("is_assembly_parent"):
        _PARENT_FAB_STRIP = {
            "laser_cutting", "laser_cutting_acrylic", "folding", "punch",
            "hole_machining", "guillotine", "plasma_cutting", "waterjet",
            "drilling", "tapping", "countersinking",
        }
        # EVERY TIME MAP, not two of five. estimate_process_times returns setup_times_min,
        # run_times_min_per_unit, unit_times_min and times_min — the last two derived from
        # the first two and built BEFORE this strip runs. Popping only the first two left a
        # part record that says "does not fold" in one map and "folds" in another.
        #
        # That inconsistency is what produced missing_labour_rate:folding on 12120's 101 and
        # 103. The risk flag is computed from times_min (estimator.py:3224) as
        # requested_ops - costed_ops: folding survived in times_min, was correctly NOT costed
        # because the strip had removed it from the maps costing reads, and the subtraction
        # reported it as an operation with no configured rate. It reads as under-costing —
        # work identified and not priced — when the truth is the opposite: the fold belongs
        # to the CHILDREN, they carry it, and suppressing it on the parent is correct. The
        # flag sent an estimator looking for a missing rate that was never missing.
        for _bucket in ("run_times_min_per_unit", "setup_times_min",
                        "unit_times_min", "times_min"):
            _m = process.get(_bucket)
            if isinstance(_m, dict):
                for _op in [o for o in _m if o in _PARENT_FAB_STRIP]:
                    _m.pop(_op, None)
        # The totals are sums of those maps and go stale the moment anything is removed.
        try:
            process["unit_time_min"] = round(
                sum((process.get("unit_times_min") or {}).values()), 2)
            process["total_time_min"] = round(
                sum((process.get("times_min") or {}).values()), 2)
        except Exception:
            pass
        process["assembly_parent_fab_suppressed"] = True

    # ── A BOARD ASSEMBLY IS FITTED BEFORE IT IS PACKED ───────────────────────────────────
    #
    # "No bench work time" — Tony Ford, 11908-21. BENC is 25.5 of his 42 hours, the single
    # biggest operation on the job, and the engine charged NONE of it. Not a wrong rate: the
    # operation never existed, and the reason is one line in the workbook's op map.
    #
    # Every non-welded assembly node mints ONE `assembly` event. For board,
    # OP_NAME_MAP_JOINERY sends "assembly" to Packing Joinery — so a tray's assembly event
    # became its PACKING row, and the fitting that produced the tray was charged as boxing
    # it. One event doing two jobs, and landing on the wrong one. Tony's sheet has both,
    # because they are both real: BENC to fit it together, PACJ to box it.
    #
    # THE EVIDENCE IS THE BOM'S OWN STRUCTURE — a parent with more than one child has to be
    # put together before it can be packed — which is the same standard the assembly event
    # itself is minted on, not a new inference. Gated to board so no metal or acrylic job
    # moves: an acrylic display really is assembled and packed in one PACP pass, which is
    # what Howard's "Apply Tape, Bag, Bulk Pack" describes.
    # THE RULE IS GENERIC; THE RATE IS NOT. A multi-part board assembly has to be fitted
    # before it is packed, whatever the board is — that follows from the BOM's own
    # structure. Tony's 2/hr came off ONE faced-board tray, and the first cut of this let it
    # reach plywood, timber and plain MDF simply because they had children. That is the
    # scoped-pilot-becoming-a-constant fault, in the change made to fix a different one.
    #
    # So: inside his scope (faced/laminated board, the family he measured) the line takes his
    # measured rate. Outside it the line still EXISTS — silence would be the bigger error —
    # and takes the house bench allowance, saying plainly that it is a general figure and
    # that his pilot does not govern it.
    _mat_bench = str(part.get("normalized_material") or "").upper().replace("_", " ")
    _is_board_asm = (
        any(_w in _mat_bench for _w in ("MDF", "MFMDF", "MFC", "CHIPBOARD", "PLYWOOD",
                                        "PLY", "TIMBER", "BIRCH", "VENEER", "LAMINATE"))
        and (part.get("is_assembly_parent") or part.get("assembly_children")
             or str(part.get("canonical_kind") or "").lower() == "assembly"))
    _in_tony_scope = any(_w in _mat_bench for _w in ("MFMDF", "MFC")) or bool(
        part.get("_laminate_in_board")
        or str(part.get("_stated_faced_family") or "").upper() in {"MFMDF", "MFC"}
        or str((part.get("material_estimate") or {}).get("costing_material_family")
               or "").upper() in {"MFMDF", "MFC"})
    if _is_board_asm and not part.get("bench_work_applied"):
        _rt_b = process.setdefault("run_times_min_per_unit", {})
        _st_b = process.setdefault("setup_times_min", {})
        # THE MINUTES COME FROM THE REGISTER'S RUN RATE, not from the generic 2-minute
        # bench default, so the engine and the workbook agree instead of relying on the
        # throughput guard to correct a figure we already know. Tony's 2/hr is 30 minutes a
        # tray; the set-up is the department's own and is charged once per order, which is
        # why it is NOT added here.
        _house_min = float((config.LABOUR_RULES.get("bench_work") or {}).get(
            "min_per_part", 2.0))
        _bench_rate = float((getattr(config, "SHOP_STATED", None) or {}).get(
            "joinery_bench_parts_per_hour") or 0.0)
        if _in_tony_scope and _bench_rate > 0:
            _bench_min = 60.0 / _bench_rate
            _bench_why = (f"the joinery bench run rate "
                          f"({config.shop_stated_source('joinery_bench_parts_per_hour')}), "
                          f"a SCOPED PILOT measured on faced/laminated board")
        else:
            _bench_min = _house_min
            _bench_why = (f"the house bench allowance — this assembly is {_mat_bench or 'board'}, "
                          f"OUTSIDE the faced/laminated board the "
                          f"{config.SHOP_STATED.get('joinery_rates_measured_on_job')} pilot "
                          f"was measured on, so that rate does NOT govern it")
        _rt_b["bench_work"] = round(_rt_b.get("bench_work", 0.0) + _bench_min, 4)
        part["bench_work_applied"] = True
        record_operation(part, "bench_work", "joinery_route_rule")
        part.setdefault("review_flags", []).append(
            f"bench fitting: {_bench_min:g} min of Bench Work Joinery on this board "
            f"assembly before it is packed. THE DRAWING DOES NOT ANNOTATE THIS — it is the "
            f"assembly's own structure ({len(part.get('assembly_children') or []) or 'its'} "
            f"children have to be put together) costed at {_bench_why}, with the "
            f"department's set-up charged once per order. Confirm it applies to an "
            f"assembly this size")

    # Acrylic route, costed the SDI way (canonical model from the M18 workbook). The laser
    # op is recomputed to the SDI acrylic model — load/unload (per sheet ÷ parts nested) +
    # profile cut (perimeter ÷ speed) + hole cutting — then estimate_labour_costs applies the
    # LASA rate. Linebend scales per bend. Glue + flame-polish are ONE op per bonded/display
    # assembly, attached to the FORMED (bent) body panel so a multi-panel tank isn't charged
    # per panel. All time-drivers in config.ACRYLIC_OP_DRIVERS.
    _mat_acr2 = str(part.get("normalized_material") or "").upper().replace("_", " ")
    if _mat_acr2 in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"} and not part.get("is_assembly_parent"):
        _drv = getattr(config, "ACRYLIC_OP_DRIVERS", {}) or {}
        _rt = process.setdefault("run_times_min_per_unit", {})
        _st = process.setdefault("setup_times_min", {})
        _ng = part.get("normalized_geometry") or {}
        _geom = part.get("dxf_raw_geometry") or {}
        _L = _safe_float(part.get("overall_length_mm")) or _safe_float(_ng.get("blank_length_mm")) or 0.0
        _W = _safe_float(part.get("overall_width_mm")) or _safe_float(_ng.get("blank_width_mm")) or 0.0
        _holes = _safe_int(part.get("hole_count")) or _safe_int(_geom.get("estimated_hole_count")) or 0
        _bends = _safe_int(part.get("bend_count_dxf")) or _safe_int(_geom.get("estimated_bend_line_count")) or 0
        # THE BEND SURVIVES THE READER THAT WON. On 10975-02 the native flat pattern beat
        # the 2 mm DXF for geometry but published no bend count, so _bends was 0, Linebend
        # was never booked, and the part's two heat-bends (DOWN 90 / UP 180 on the drawing)
        # were formed for free — the mirror of the 7332 fold bug: the wrong op was stopped
        # and the right one never charged. When no reader counted bends, the drawing's own
        # callouts and the model's feature count still testify; only a model that MEASURED
        # zero bends says the part is flat.
        if not _bends and not _model_measured_zero_bends(part):
            _bends = (_safe_int((part.get("manufacturing_features") or {}).get("bend_count"))
                      or _safe_int(part.get("fold_count_textual"))
                      or len(part.get("angles_deg") or []))
        if _L > 0 and _W > 0:
            _spd = float(_drv.get("laser_cut_mm_per_sec", 50.0)) or 50.0
            _pps = (select_sheet_size(part.get("normalized_material"), _L, _W) or {}).get("parts_per_sheet") or 1
            _pps = max(1, int(_pps))
            _laser_sec = (
                float(_drv.get("laser_load_unload_sec_per_sheet", 300.0)) / _pps
                + (2.0 * (_L + _W)) / _spd
                + _holes * float(_drv.get("laser_sec_per_hole", 3.0))
            )
            _rt["laser_cutting"] = round(_laser_sec / 60.0, 4)   # LASA rate applied by labour-coster
            _st.setdefault("laser_cutting", float(_drv.get("laser_setup_min", 5.0)))
        # acrylic_route_v2 (2026-07-15): route matches the estimator's acrylic sheets.
        # An acrylic part is SIMPLER than metal. Every acrylic part gets Diamond Polish
        # (the finish — acrylic is NOT powder coated) and Peel (protective film). Linebend
        # scales per bend. GLUE + flame are added ONLY for a genuinely BONDED assembly
        # (multi-panel display / tank), never for a single formed part. LASER is added only
        # when there is an actual laser-cut signal; a lone formed part from sheet is
        # guillotine/router + line-bent, not lasered.

        # Is this a bonded multi-panel assembly (glue + flame apply), or a single formed part?
        _bonded = bool(part.get("is_bonded_assembly")) or bool(part.get("acrylic_bonded"))
        _kids = part.get("child_parts") or part.get("children") or []
        if not _bonded and isinstance(_kids, (list, tuple)) and len(_kids) >= 2:
            _bonded = True   # multiple bonded panels under this part

        # Is the part actually laser-cut? Only then does laser apply. Absent a signal, a
        # single formed acrylic part is not lasered (matches the estimator).
        _laser_signal = bool(part.get("is_laser_cut")) or bool(part.get("laser_cut_acrylic"))
        _cut_method = str(part.get("cut_method") or part.get("cutting_method") or "").lower()
        if "laser" in _cut_method:
            _laser_signal = True
        if _cut_method in ("guillotine", "router", "rout", "saw", "cnc_rout"):
            _laser_signal = False
        if not (_laser_signal or _bonded):
            # not lasered: drop the laser op the block added above
            _rt.pop("laser_cutting", None)
            _st.pop("laser_cutting", None)

        # FINISH: Diamond Polish for every acrylic part; powder is invalid on acrylic.
        _rt["diamond_polish"] = round(_rt.get("diamond_polish", 0.0)
                                      + float(_drv.get("diamond_polish_min_per_part", 0.5)), 4)
        _st.setdefault("diamond_polish", float(_drv.get("diamond_polish_setup_min", 10.0)))
        # ── THE PEEL ALLOWANCE COMES OFF, BECAUSE THE SHOP SAYS IT IS NOT A THING ──────
        #
        # This booked "peel the protective film" as a Manual Labour (Acrylic) line on
        # every acrylic part — the engine's standard allowance, read off nothing. Howard
        # Thurley, asked directly whether his sheet carries it ("Manual Labour Acrylic
        # allowing – no additional op. on manual estimating sheet – is this Peel?"):
        #
        #   "Subjective – depends on component, peel may be incorporated into individual
        #    operations. Nothing fixed for this."
        #
        # A default the department itself calls not-fixed is this engine inventing a
        # standing charge. So it is booked ONLY where the drawing states the work —
        # peel / protective film / masking in the part's own text — and otherwise the
        # line does not exist and the record says why, so the absence is a decision a
        # person can reverse, not a gap.
        _peel_text = " ".join(
            str(x) for x in ([part.get("description")]
                             + list(part.get("textual_operations") or [])
                             + list(part.get("process_notes") or []))).upper()
        if any(_w in _peel_text for _w in ("PEEL", "PROTECTIVE FILM", "MASKING", "DEMASK")):
            _rt["manual_labour_acrylic"] = round(
                _rt.get("manual_labour_acrylic", 0.0)
                + float(_drv.get("peel_min_per_part", 0.5)), 4)
            _st.setdefault("manual_labour_acrylic", float(_drv.get("peel_setup_min", 15.0)))
            part.setdefault("review_flags", []).append(
                "Manual Labour (Acrylic): peel/masking charged because the drawing's own "
                "text states it — the shop has no fixed allowance for this "
                "(Howard Thurley: 'Subjective – depends on component'), so confirm the "
                "minutes fit this component")
        elif not part.get("_acrylic_peel_declined"):
            part["_acrylic_peel_declined"] = True
            part.setdefault("review_flags", []).append(
                "Manual Labour (Acrylic): NO default handling/peel allowance charged. The "
                "shop has nothing fixed for this — Howard Thurley: 'Subjective – depends "
                "on component, peel may be incorporated into individual operations. "
                "Nothing fixed for this.' If this component needs a hand operation, state "
                "it with a time and it will be charged as stated")
        # Acrylic is never powder coated — strip any powder op the finish-resolver added.
        for _pw in ("powder_coating",):
            _rt.pop(_pw, None)
            _st.pop(_pw, None)
        part["acrylic_no_powder"] = True   # signal downstream: suppress the powder BOM line
        # And never press-braked. A "DOWN 90°" callout in the drawing text raises FOLD long
        # before this branch runs; the forming is real but it is the line-bender's, and it
        # is booked as Linebend from the bend count below. Leaving the metal fold's minutes
        # in the time-map would charge the same two bends twice.
        for _fl in ("folding", "fold"):
            _rt.pop(_fl, None)
            _st.pop(_fl, None)

        if _bends > 0:
            _rt["linebend"] = round(_rt.get("linebend", 0.0) + float(_drv.get("min_per_linebend", 1.0)) * _bends, 4)
            _st.setdefault("linebend", float(_drv.get("linebend_setup_min", 30.0)))

        if _bonded:
            # bonded multi-panel assembly: glue joints + flame-polish, ONE op per assembly
            _rt["glue"] = round(_rt.get("glue", 0.0) + float(_drv.get("glue_min_per_assembly", 2.4)), 4)
            _st.setdefault("glue", float(_drv.get("glue_setup_min", 30.0)))
            _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0) + float(_drv.get("flame_min_per_assembly", 1.2)), 4)
            _st.setdefault("manual_labour_acrylic", float(_drv.get("flame_setup_min", 15.0)))

        # THE COMPILER HAS TO KNOW ABOUT AN OP TO CHARGE IT UNDER CUTOVER. These acrylic ops
        # are written straight into the process time-map — they are the acrylic route itself,
        # not words read off the drawing — so nothing put them on the part's operation list.
        # Under the canonical-route cutover a required OperationDecision is the ONLY thing that
        # becomes a labour row, so an op the compiler never saw was priced by the estimator and
        # then silently dropped from the sheet: 7332-01-007's lens carried a Diamond Polish the
        # workbook never charged. Record each acrylic op that actually survives in the time-map
        # (laser is popped above when the part is not lasered) so the compiler raises a required
        # decision for it and the cutover charges exactly what the estimator costed.
        for _acr_op in ("laser_cutting", "diamond_polish", "manual_labour_acrylic",
                        "linebend", "glue"):
            if _rt.get(_acr_op) or _st.get(_acr_op):
                record_operation(part, _acr_op, "acrylic_route_rule")

        process["acrylic_ops_canonical"] = True
        process["acrylic_route_v2"] = True
        process["acrylic_bonded_detected"] = _bonded
        process["acrylic_laser_applied"] = bool(_laser_signal or _bonded)

    labour = estimate_labour_costs(process, job_quantity=order_qty, material=part.get("normalized_material"))
    if debug:
        print(f"[DEBUG] estimate_part labour done {part_number}")
    system_cost = _resolve_part_system_cost(part)
    if debug:
        print(f"[DEBUG] estimate_part system_cost done {part_number}")
    system_unit_cost = _safe_float(system_cost.get("applied_unit_cost"))
    system_cost_result = system_cost.get("result", {})
    matched_part_code = system_cost.get("matched_part_code")
    _bought_in_fitting_gbp = None

    # A STANDARD-COMMODITY PROVISIONAL IS A MATERIAL BUY, PRICED AT ITS CONFIG FIGURE.
    #
    # The provisional (a pallet, a perforated-panel clip) is the price we PAY for the item. It
    # belongs in the material column at exactly that figure — so the BOM shows the buy price,
    # not a labour number, and the total carries the price the config names. The general bought-in
    # path below adds a bench-fitting uplift on top of the buy and leaves the material column to be
    # back-derived as (unit total − labour), which reads a fitting cost as material and lands the
    # clip at £1.82 for a £1.20 buy. A standard commodity is placed during the assembly labour the
    # parent already carries, so it takes no fitting of its own: route the figure straight to
    # material and skip the uplift. Only the reproducible provisional source — every real
    # catalogue/UDEF bought-in keeps the fitting path unchanged.
    _is_commodity_provisional = (
        system_unit_cost is not None
        and str((_extract_selected_price(system_cost_result) or {}).get("source") or "")
        == "standard_commodity_provisional")
    if _is_commodity_provisional:
        _com_unit = round(float(system_unit_cost), 4)
        material["unit_material_cost_gbp"] = _com_unit
        material["cost_per_part_gbp"] = _com_unit
        material["extended_material_cost_gbp"] = round(_com_unit * quantity, 4)
        material.setdefault("cost_method", "standard_commodity_provisional")

    material_extended = material.get("extended_material_cost_gbp")
    extended_material_cost = _safe_float(material_extended) or 0.0
    total_labour_cost = labour.get("total_labour_cost_gbp") or 0.0

    # Default laser_cutting for any fabricated sheet metal part that has blank
    # dimensions but no cutting op detected — all sheet parts start on the laser.
    _mat_upper = str(part.get("normalized_material") or "").upper()
    _is_sheet_metal = _mat_upper in {
        "MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
        "ALUMINIUM", "ALUMINUM", "ZINTEC",
    }
    _has_blank = bool(
        _safe_float(part.get("blank_length_mm")) or
        _safe_float(part.get("overall_length_mm")) or
        _safe_float(part.get("normalized_thickness_mm"))
    )
    _existing_ops = list(_part_ops(part) or [])
    _cutting_ops = {"laser_cutting", "guillotine", "plasma_cutting", "waterjet"}
    if _is_sheet_metal and _has_blank and not any(op in _cutting_ops for op in _existing_ops):
        record_operation(part, "laser_cutting", "inference", inferred=False)

    op_set = {str(op).strip().lower() for op in _part_ops(part) if str(op).strip()}
    no_ops_except_handling = op_set <= {"handling"}
    desc_blob = " ".join(
        [
            str(part.get("description") or ""),
            ";".join(part.get("process_notes") or []),
            ";".join(_part_ops(part) or []),
        ]
    ).upper()
    # ── A PART IN THE BUILD GETS A PRICE ────────────────────────────────────────────
    #
    # James Gray, 18 September 2026:
    #
    #     "we price everything. we dont drop something if it's obviously something that is
    #      part of the unit."
    #
    # THIS RETURNED £0.00 BEFORE THE WATERFALL BEGAN. Any part whose normalised material was
    # BOUGHT_IN, PAPER or PRINTED_PAPER was handed back as a complete costed part — nil
    # material, nil labour, no operations, `costing_basis: customer_supplied` — without being
    # offered to SDI Live, to a supplier catalogue, to a current quote or to researched
    # evidence. On 0355255 that is the GRAPHIC: 792 x 210, MATERIAL: PAPER, WEIGHT: 3g, one
    # of the two things the customer is buying, costed at nothing.
    #
    # BOUGHT_IN IS A SOURCING FACT, NOT A ZERO. It says SDI buys this rather than makes it,
    # which is the start of a price chain, not the end of one. The inference that somebody
    # else pays for it was never in the material name — a part can be bought in and still be
    # ours to buy, which is the ordinary case.
    #
    # FREE ISSUE STILL EXISTS AND IS STILL FREE. It is a DECISION — the estimator rules that
    # the customer supplies this item — and it already has its own representation, its own
    # nil_by_design classification and its own sentence, which even now ends "if SDI is buying
    # it, enter the rate". That sentence was written because this assumption was known to be
    # wrong sometimes. It is a person's ruling and it is recorded as one; it is not something
    # to be read off a material string.
    #
    # So the line falls through to the bought-in price chain below like every other purchased
    # item, and where nothing prices it the estimator gets one action instead of a zero that
    # sums as free.

    bought_in_keywords = (
        "BOUGHT IN",
        "BOUGHT-IN",
        "PURCHASED",
        "OFF THE SHELF",
        "CATALOGUE",
        "CATALOG",
        "HARDWARE",
        "CASTOR",
        "CASTER",
        "TENTE",
        "STEM",
        "BUSH",
        "FIXING",
        "SCREW",
        "WOOD SCREW",
        "WOODSCREW",
        "KNURLED",
        "UPC STICKER",
        "STICKER",
        "VINYL",
        "PALLET",
        "LENS COVER",
        "UPC",
        "HINGE",
        "HAFELE",
        "FINGER PULL",
        "HANDLE",
        "DOWEL",
        "T-NUT",
        "PEM STUD",
        "THREADED INSERT",
        "WOODEN DOWEL",
        "MOUNTING PLATE",
    )
    bought_in_candidate = (no_ops_except_handling and not part.get("flat_pattern_detected")) or any(
        k in desc_blob for k in bought_in_keywords
    )

    # GUARD 1 — A part the inference engine is provisionally costing is an SDI
    # FABRICATED part, not a catalogue buy. Routing it through the system-cost
    # (catalogue) match produces wild fuzzy-match prices (e.g. "BRACKET" -> £13k).
    if part.get("geometry_inferred"):
        bought_in_candidate = False

    # A special finishing item (tiles/mosaic/graphic/vinyl, -X suffix) is bought in, not
    # fabricated — even when the engine gave it provisional geometry. Price it via the
    # bought-in path (UDEF match, or left flagged/unpriced if nothing matches). Overrides
    # GUARD 1; the plausibility cap (GUARD 2) below still applies.
    if part.get("special_finish_item"):
        bought_in_candidate = True

    # GUARD 2 — Plausibility cap on the matched system cost. A genuine bought-in
    # fitting (castor, hinge, screw, Hafele part) is cheap. A four/five-figure hit
    # is a bad fuzzy match (catalogue assembly price, per-tonne value, or wrong code)
    # OR a genuine high-value buy that MUST get a human look — either way it is never
    # safe to apply silently to an auto-detected bought-in line. Reject + flag.
    if bought_in_candidate and system_unit_cost is not None:
        _max_plausible = float(getattr(config, "BOUGHT_IN_MAX_PLAUSIBLE_GBP", 750.0) or 750.0)
        if float(system_unit_cost) > _max_plausible:
            part.setdefault("risk_flags", []).append(
                f"implausible_system_cost_rejected_price_manually:GBP{float(system_unit_cost):.0f}"
            )
            bought_in_candidate = False
            system_unit_cost = None

    # A bought-in line that already carries a price from the deterministic recogniser or
    # the LLM note-scan must KEEP that price — those layers matched it to a genuine SDI
    # historical/catalogue line (e.g. Foam Tape -> "Foam Tape 890x10x1.5mm" @ £0.28). Re-
    # deriving it via the material+labour path below produced absurd figures (a £132 foam-
    # tape) because these stubs have no real geometry to cost. Respect the upstream price.
    if bought_in_candidate and system_unit_cost is not None:
        # A standard-commodity provisional takes no bench-fitting uplift — it is placed during
        # the assembly labour the parent already carries — so its unit total IS the buy price.
        #
        # AND SO DOES ANY BOUGHT-IN AN ASSEMBLY'S BOM LISTS. 11650-06: the Yiree binding screw
        # was researched at £1.25 and charged £2.29 — two minutes of handling added to the buy
        # price, on a screw that sits in a spare set packed with the kit, whose packing and
        # assembly time is already on the labour rows. The uplift is for a loose fitting that
        # nothing else accounts for; a line on an assembly's BOM is accounted for by that
        # assembly. The minutes are config, and 0 turns the uplift off everywhere.
        _owner = str(part.get("owning_assembly") or "").strip()
        if _is_commodity_provisional or (
                _owner and not getattr(config, "BOUGHT_IN_FITTING_WHEN_ON_AN_ASSEMBLY_BOM", False)):
            _fitting_cost = 0.0
        else:
            _fitting_min = _safe_float(getattr(config, "BOUGHT_IN_FITTING_MIN_PER_PART", 2.0))
            _fitting_min = 2.0 if _fitting_min is None else max(0.0, _fitting_min)
            _manm_rate = float((HOURLY_RATES_GBP or {}).get("handling", 31.18))
            _fitting_cost = (_fitting_min / 60.0) * _manm_rate
        unit_total_raw = float(system_unit_cost) + _fitting_cost
        extended_total_raw = unit_total_raw * quantity
        costing_basis = "system_cost_per_part"
        _bought_in_fitting_gbp = round(_fitting_cost, 4)
    else:
        # Material Price Break LOOKUP — workbook col J formula (rows 11-25):
        # J = LOOKUP($D$6, 'Material Price Break'!$D$4:$N$4, price_row)
        # Replicates per-line quantity-adjusted pricing from the 11-band break table.
        # When a filled Material Price Break sheet is scanned, wb_line_prices overrides the multiplier.
        qty_multiplier = _quantity_break_multiplier(quantity)
        part_number_key = str(part.get("part_number") or "").strip().upper()
        wb_line_prices: Dict[str, float] = {}  # populated from workbook scan when available
        if part_number_key in wb_line_prices:
            wb_line_cost = float(wb_line_prices[part_number_key])
            extended_total_raw = wb_line_cost * quantity
            unit_total_raw = wb_line_cost
            costing_basis = "material_price_break_lookup_workbook"
        else:
            extended_total_raw = float((extended_material_cost + total_labour_cost) * qty_multiplier)
            unit_total_raw = (extended_total_raw / quantity) if quantity else extended_total_raw
            costing_basis = f"computed_material_plus_labour_qty_break_x{qty_multiplier:.3f}"
    # ONE LINE, ONE SOURCE. A bought-in charged at its bought-in price had its material block
    # still carrying the config-rate fallback the geometry path wrote before it found nothing
    # to cut — and the AI Provenance tab reads the material block, so the Yiree screw's AI
    # market price was labelled "config_default_material_rates". Where the bought-in price is
    # what the line charges, it is the line's price source.
    _system_cost_source = _build_price_source_metadata(
        system_cost_result,
        fallback_source="system_cost_not_found",
        applied=system_unit_cost is not None,
        applied_basis="GBP_each" if system_unit_cost is not None else None,
        # The same expression as applied_to_total below, so the stamp and the
        # sibling flag cannot disagree about whether this price reached the total.
        affects_total=bool(bought_in_candidate and system_unit_cost is not None),
    )
    if costing_basis == "system_cost_per_part":
        material["price_source"] = dict(_system_cost_source)
        if _bought_in_fitting_gbp:
            material["price_source"]["bought_in_fitting_gbp_each"] = _bought_in_fitting_gbp
    unit_total = _round_money(unit_total_raw)
    extended_total = _round_money(extended_total_raw)
    markups = (WORKBOOK_EQUIVALENT_PRICING or {}).get("sell_markup_options_pct") or {"low": 10.0, "standard": 20.0, "premium": 35.0}
    margin_options: List[Dict[str, Any]] = []
    if not bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)):
        for name, pct in markups.items():
            factor = 1.0 + (float(pct) / 100.0)
            margin_options.append(
                {
                    "name": str(name),
                    "markup_pct": float(pct),
                    "unit_sell_price_gbp": round(unit_total * factor, 2),
                    "extended_sell_price_gbp": round(extended_total * factor, 2),
                }
            )

    # Surface missing price/rate conditions for human review.
    risk_flags = list(part.get("risk_flags", []))
    ps_mat = material.get("price_source") or {}
    if str(ps_mat.get("source_type") or "").lower() == "web_ai_fallback":
        risk_flags.append("web_ai_indicative_material_price")
    sc_sel = _extract_selected_price(system_cost_result) or {}
    ev_sc = sc_sel.get("evidence") or {}
    if isinstance(ev_sc, dict) and ev_sc.get("pricing_mode") == "web_ai_llm_estimate":
        risk_flags.append("web_ai_indicative_system_cost")
    section_blob = " ".join(
        [
            str(material.get("material") or ""),
            str(part.get("description") or ""),
            str(part.get("normalized_material") or ""),
        ]
    ).upper()
    if any(
        token in section_blob
        for token in (
            "TUBE",
            "RHS",
            "SHS",
            "BOX SECTION",
            "WIRE MESH",
            "WELDED WIRE",
            "LINEAR M",
            "KG/M",
        )
    ):
        risk_flags.append("section_or_wire_stock_pricing_review")

    if material.get("extended_material_cost_gbp") is None:
        if not material.get("material"):
            risk_flags.append("missing_material_spec")
        elif material.get("thickness_mm") is None:
            risk_flags.append("missing_material_thickness")
        else:
            risk_flags.append("missing_material_price")

    # ASK THE COSTER WHAT IT COULD NOT RATE, rather than subtracting two maps that disagree.
    #
    # This derived "no rate for this op" as times_min - costs_gbp. `times_min` is built BEFORE
    # the route strips run, so an op the acrylic route legitimately removed from the run/setup
    # maps still sat in the stale map and came out as a missing RATE — which is how the report
    # told an estimator that acrylic laser cutting costs nothing on 7332-01-007 while the sheet
    # charged Laser (Acrylic) £1.47 on the very same part. estimate_labour_costs already keeps
    # the honest list: it appends to missing_rate_operations only where an op HAS time and no
    # resolvable rate. One writer, one answer.
    for op in sorted(labour.get("missing_rate_operations") or []):
        risk_flags.append(f"missing_labour_rate:{op}")

    return {
        "part_number": part.get("part_number"),
        "description": part.get("description"),
        "quantity": quantity,
        # SDI Intelligence — surface material/thickness/blank dims at the top
        # level so xlsx_output Sheet Steel / Other Sheet Material sections can
        # find them (they read pe.get("normalized_material") directly).
        "normalized_material": part.get("normalized_material") or material.get("material"),
        "normalized_thickness_mm": _safe_thickness_mm(part) or material.get("thickness_mm"),
        # WHERE THOSE TWO NUMBERS CAME FROM TRAVELS WITH THEM.
        #
        # THE THIRD AND FOURTH TIME A FACT STOPPED AT THIS BOUNDARY. geometry_rollup and
        # page_roles are both above, each with its own note about a reader that asked the
        # costed record a question the raw record could answer. This is the same defect on
        # the fields that decide the price: the VALUE was copied here and its SOURCE was not.
        #
        # So every reader downstream of costing is provenance-blind. A diagnostic run to
        # explain why 11650-04's handed side panels disagreed printed "(no source recorded)"
        # for material, gauge and quantity on all four parts -- while the raw records
        # carried mirror_of_measured, a dxf reading and a recorded refusal between them. An
        # absence reported as a clean answer, in the tool built to stop exactly that.
        #
        # KEYED OFF THE RESOLVER, not a list typed here. Three of these do not follow the
        # "<field>_source" convention, and a fourth arbitrated field would otherwise cross
        # the boundary as a value with no source and look like a guess.
        **{_k: part.get(_k) for _k in source_precedence._SOURCE_FIELDS.values()
           if part.get(_k) is not None},
        # WHAT THE WINNER BEAT. displaced_values is the whole evidence base for asking
        # whether independent lower-ranked sources agreed against a lone higher-ranked one
        # -- the door's ABS-over-polycarbonate, the side panel's ABS-over-PETG. Left behind
        # here, that question can only be asked before costing and never explained after.
        **({"_displaced": part.get("_displaced")} if part.get("_displaced") else {}),
        # THE LAYERS A LAMINATION IS MADE OF, ALONGSIDE WHAT THEY COST.
        #
        # The same boundary defect as the two above, caught before it shipped rather than
        # after: material_estimate crosses here carrying material_layers_priced, and the
        # DECLARATION of what layers exist did not. The check that asks "did every declared
        # layer reach the price?" reads the costed record, so without this it would find the
        # answer and never the question — len(layers) < 2, short-circuit, silent pass. A
        # check that cannot see what it is checking is worse than no check, because it
        # reports CLEAR.
        **({"material_layers": part.get("material_layers")}
           if part.get("material_layers") else {}),
        "material_estimate": material,
        "process_estimate": process,
        "labour_estimate": labour,
        "normalized_geometry": part.get("normalized_geometry", {}),
        # THE ROLLUP TRAVELS WITH THE MONEY, TOO.
        #
        # normalized_geometry was copied here and geometry_rollup was not, so every reader
        # that asks the costed record for `geometry_rollup` — and wb_populate's laser
        # calculator is one, by name, in its own comment — got None on every part of every
        # job and silently fell through to whatever it had listed as its rescue.
        #
        # The two records are not the same record. normalized_geometry carries the
        # DERIVED, confidence-weighted view (`hole_count`, `cut_length_mm`); the rollup
        # carries the MEASURED one (`estimated_hole_count`, `estimated_cut_length_mm`).
        # Where the derived view is silent the measured one was simply unreachable.
        #
        # 11350's right hand is what this cost. The mirror pass filled its rollup from the
        # measured left hand — 743.99mm of cut, 2 holes, confirmed present on the raw
        # record — and none of it reached the sheet, because the only pool the sheet reads
        # is this dict. The part laser-cut at 368/hr against its own mirror image's 287.
        "geometry_rollup": part.get("geometry_rollup") or {},
        # WHAT THE PART IS FOR TRAVELS WITH THE MONEY TOO.
        #
        # wb_populate decides which block a part belongs in from `page_roles` — a
        # 'bought_in' role is what puts a hardware line on the BOM with its own price. The
        # raw record carries it and the costed one did not, so the workbook asked a part
        # what it was for and got nothing back.
        #
        # 12422-24's LOW068 is what that costs. The raw record reads
        # roles ['assembly', 'bought_in']; the costed record reads None; and the workbook
        # says "LOW068 unclassifiable (stock_form='', role=[], ...) - skipped". Two
        # adjustable feet, correctly identified, correctly coded, dropped off the estimate
        # because the one field that says what they are stopped at the costing boundary.
        "page_roles": list(part.get("page_roles") or []),
        "roles": list(part.get("roles") or []),
        # The model's plate verdict travels with the costed record. It was set on the raw
        # part and never copied here, so the record that carries the folding MONEY had no
        # idea the part was flat, and nothing downstream could compare the two.
        "native_flat_solid": part.get("native_flat_solid"),
        # THE SUBSTITUTION TRAVELS WITH THE COSTED RECORD, OR IT DOES NOT TRAVEL.
        #
        # apply_production_substitutions records the 0.9-to-1.0 rule on the RAW part and
        # pushes the substitute through source_precedence onto normalized_thickness_mm.
        # That was its only route to the sheet, and the sheet writes the gauge from the
        # COSTED record — so if the costed record's gauge came from anywhere else, the
        # book showed the drawn 0.9 and the whole row costed from it, with nothing on the
        # sheet to say a substitution had ever been decided. Exactly the wrong-record
        # shape as the tube-bend ruling: the fact was right and unreachable.
        #
        # Both halves come across: what the drawing says, and what production buys.
        "production_substitution": (dict(part["production_substitution"])
                                    if isinstance(part.get("production_substitution"), dict)
                                    else None),
        "drawn_thickness_mm": part.get("drawn_thickness_mm"),
        # Preserve the evidence which explains the route on the costed record. This nested
        # field is shadow-only during migration: no existing workbook consumer reads it, so
        # adding it cannot alter a price or labour row.
        "route_context": {
            "textual_operations": list(part.get("textual_operations") or []),
            "inferred_operations": list(part.get("inferred_operations") or []),
            "operations": list(part.get("operations") or []),
            "operation_sources": dict(part.get("operation_sources") or {}),
            "operation_sequence": dict(part.get("operation_sequence") or {}),
            "operation_scope": dict(part.get("operation_scope") or {}),
            "operation_qty_per_unit": dict(
                part.get("operation_qty_per_unit") or {}),
            "operation_department_read": dict(
                part.get("operation_department_read") or {}),
            "operations_ruled_out": dict(part.get("operations_ruled_out") or {}),
            "operation_ruling_sources": dict(
                part.get("operation_ruling_sources") or {}),
            "is_sub_assembly": bool(part.get("is_sub_assembly")),
            "is_assembly_parent": bool(part.get("is_assembly_parent")),
        },
        "cost_breakdown": {
            "material": {
                "unit_material_mass_kg": material.get("unit_material_mass_kg"),
                "unit_material_cost_gbp": material.get("unit_material_cost_gbp"),
                "extended_sheet_material_cost_gbp": material.get("extended_sheet_material_cost_gbp"),
                "powder_consumable": material.get("powder_consumable"),
                "extended_material_cost_gbp": material.get("extended_material_cost_gbp"),
                "supplier_source": material.get("price_source", {}).get("supplier_source"),
                "price_date": material.get("price_source", {}).get("price_date"),
            },
            "labour": {
                "unit_time_min": process.get("unit_time_min"),
                "total_time_min": process.get("total_time_min"),
                "costs_gbp": labour.get("costs_gbp", {}),
                "total_labour_cost_gbp": labour.get("total_labour_cost_gbp"),
                "rate_sources": labour.get("rate_sources", {}),
            },
            "system_cost": {
                "unit_cost_gbp": round(system_unit_cost, 2) if system_unit_cost is not None else None,
                "extended_cost_gbp": round((system_unit_cost or 0.0) * quantity, 2) if system_unit_cost is not None else None,
                "matched_part_code": matched_part_code,
                "part_description": part.get("description"),
                "source": _system_cost_source,
                "applied_to_total": bought_in_candidate and system_unit_cost is not None,
                "fitting_gbp_each": _bought_in_fitting_gbp,
                "owning_assembly": part.get("owning_assembly") or None,
            },
            "overhead": {
                "unit_overhead_cost_gbp": None,
                "extended_overhead_cost_gbp": None,
            },
            "unit_total_cost_gbp": unit_total,
            "extended_total_cost_gbp": extended_total,
            "costing_basis": costing_basis,
            "margin_options": margin_options,
            "assumptions": {
                "material_price_source": material.get("price_source", {}),
                "labour_model": "external_or_config_fallback",
                "geometry_basis": "normalized_geometry",
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "part_provenance_source": (part.get("provenance") or {}).get("source"),
            },
        },
        "alternative_processes": [],
        "unit_total_cost_gbp": unit_total,
        "extended_total_cost_gbp": extended_total,
        "unit_total_cost_raw_gbp": unit_total_raw,
        "extended_total_cost_raw_gbp": extended_total_raw,
        "notes": [
            "Geometry-derived timings are heuristic until calibrated against known jobs.",
            "Primary dimensions are inferred from extracted values; verify against the drawing before quoting.",
        ],
        "part_provenance": part.get("provenance", {}),
        "part_confidence": part.get("confidence", {}),
        "risk_flags": risk_flags,
        # Stamped during process costing — Basis & Provisos reads these from the part record.
        "punch_calibration": part.get("punch_calibration"),
        "section_costing_adjustment": part.get("section_costing_adjustment"),
        "review_flags": part.get("review_flags") or [],
    }


def _build_workbook_equivalent_pricing(part_estimates: List[Dict[str, Any]],
                                       material_total: float, labour_total: float,
                                       customer: Any = None) -> Dict[str, Any]:
    cfg = WORKBOOK_EQUIVALENT_PRICING or {}
    # Exact workbook M105: =((M59+M103)/(1-M107))/0.92
    # overhead_absorption_factor = 0.92 hard-coded in the workbook cell (~8.7% overhead uplift).
    # M107 = rebate fraction (TTI default 0.066). M109 = sell margin (blank=0, estimator fills in).
    overhead_factor = float(cfg.get("overhead_absorption_factor", 0.92))
    m107 = float(cfg.get("default_m107", 0.066))
    # THE CUSTOMER'S OWN TERMS BEAT THE CONFIG DEFAULT. The office books M&S at a 1.8%
    # rebate over /0.92 and TTI at 6.6% over /0.93 (their own table, via Tony Ford's
    # 0359967); a single default is right for at most one of them. The workbook cells are
    # set by wb_populate from the same config table, so the two answers cannot diverge.
    _terms_fn = getattr(config, "customer_commercial_terms", None)
    _terms = _terms_fn(customer) if callable(_terms_fn) else None
    if _terms:
        m107 = float(_terms["rebate_fraction"])
        overhead_factor = float(_terms["absorption_divisor"])
    m109 = float(cfg.get("default_m109", 0.0))
    m59 = round(material_total, 4)
    m103 = round(labour_total, 4)
    denominator_m107 = max(0.0001, 1.0 - m107)
    denominator_m109 = max(0.0001, 1.0 - m109)
    m105 = round(((m59 + m103) / denominator_m107) / overhead_factor, 4)
    l111 = round(m105 / denominator_m109, 4)
    labour_hours_total = round(
        sum((_safe_float(item.get("process_estimate", {}).get("total_time_min")) or 0.0) / 60.0 for item in part_estimates),
        4,
    )
    manufacturing_only = bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False))
    result: Dict[str, Any] = {
        "m59_material_subtotal_gbp": m59,
        "m103_labour_subtotal_gbp": m103,
        "m107_rebate_fraction": m107,
        "m109_sell_margin_fraction": m109,
        "overhead_absorption_factor": overhead_factor,
        "m105_total_unit_cost_gbp": m105,
        "l105_total_unit_cost_gbp": m105,
        "l111_sell_price_gbp": l111,
        "labour_hours_total": labour_hours_total,
        "formula_strings": {
            "m105": "=((M59+M103)/(1-M107))/overhead_absorption_factor",
            "l111": "=M105/(1-M109)",
            "note": "overhead_absorption_factor=0.92 hard-coded in workbook. M107=rebate (TTI 0.066). M109=sell margin (estimator fills in).",
        },
        "assumptions": {
            "overhead_absorption_factor": overhead_factor,
            "rebate_fraction": m107,
            "sell_margin_fraction": m109,
            "source": ("customer_commercial_terms" if _terms
                       else "workbook_equivalent_pricing"),
            **({"customer_terms": _terms} if _terms else {}),
        },
    }
    if manufacturing_only:
        result["l111_sell_price_gbp"] = None
        result["assumptions"]["sell_price_suppressed"] = True
        result["assumptions"]["sell_price_reason"] = "OUTPUT_MANUFACTURING_COST_ONLY"
    return result


def _page_text_for_bought_in_scan(page: Dict[str, Any]) -> str:
    """Join all likely text fields from a scan summary page (structure varies by pipeline stage)."""
    chunks: List[str] = []
    rt = page.get("region_text") or {}
    if isinstance(rt, dict):
        for v in rt.values():
            if v:
                chunks.append(str(v))
    for key in ("pdfplumber_text", "normalized_text", "pypdf_text", "text", "text_preview"):
        v = page.get(key)
        if v:
            chunks.append(str(v))
    ps = page.get("pattern_summary") or {}
    if isinstance(ps, dict):
        raw = ps.get("raw_text")
        if raw:
            chunks.append(str(raw))
    return " ".join(chunks)


def _announce_packing_status(cline: Dict[str, Any]) -> None:
    """SAID ON THE RUN. The 18:21 book's packing zero was undiagnosable from the
    deliverables — the reason lived in one JSON field. Module-level so a test can prove
    the sentence is actually printed, not merely present in the source."""
    if isinstance(cline, dict) and cline.get("method_status"):
        print(f"   [packing] {cline['method_status']}", flush=True)


def _bought_in_part_stub(part_number: str, description: str, quantity: Any) -> Dict[str, Any]:
    """Minimal shape compatible with document_builder + estimate_part.

    THE ONE PLACE A PURCHASED PART IS BORN. Every reader that finds a bought-in — the
    catalogue layer, the prose recogniser, the note scan, the BOM rows — comes through here,
    which is why the manufacturer reference is captured here and not in any of them. Capturing
    it per reader is how three of the four would have gone on discarding it.
    """
    stub = {
        "part_number": part_number,
        "description": description,
        "quantity": quantity,
        "pages": [],
        "page_roles": ["bought_in"],
        "materials": [],
        "surface_finishes": [],
        "colours": [],
        "thicknesses_mm": [],
        "weights": [],
        "textual_operations": ["handling"],
        "inferred_operations": [],
        "flat_pattern_detected": False,
        "assembly_candidate": False,
        "process_notes": [],
        "review_flags": [],
        "confidence": {},
        "geometry_rollup": {
            "vector_path_count": 0,
            "line_segments": 0,
            "rectangles": 0,
            "curves": 0,
            "filled_paths": 0,
            "approx_total_line_length_points": 0.0,
            "approx_total_curve_length_points": 0.0,
            "estimated_cut_length_mm": 0.0,
            "estimated_hole_count": 0,
            "estimated_circle_like_features": 0,
            "estimated_slot_like_features": 0,
            "estimated_bend_line_count": 0,
            "estimated_pierce_count": 0,
            "contour_complexity": 0,
            "closed_path_count": 0,
            "long_axis_aligned_lines": 0,
            "dashed_long_axis_lines": 0,
            "confidence": {
                "geometry_reliability": 0.0,
                "estimated_cut_length_mm": 0.0,
                "estimated_hole_count": 0.0,
                "estimated_slot_like_features": 0.0,
                "estimated_bend_line_count": 0.0,
            },
        },
        "hole_sizes_mm": [],
        "angles_deg": [],
        "slot_detected": False,
        "slot_sizes_mm": [],
        "mirrored_detected": False,
        "manufacturing_features": {},
        "manufacturing_interpretation": {"routing": [{"operation": "handling", "phase": "logistics", "driver": "part_count", "source": "default"}]},
        "risk_flags": [],
        "normalized_material": None,
        "normalized_finish": None,
        "normalized_thickness_mm": None,
        "_bought_in_from_text_scan": True,
    }

    # THE RATE WE ALREADY HOLD, APPLIED WHERE THE PART IS BORN.
    #
    # The commodity table was consulted in estimate_part, under one branch — the records
    # whose `source` is "sdi_bom_code_unpriced". 12349-02's wood screw and M4 button head are
    # not those: their line on the sheet reads a bare "MATERIAL UNPRICED: enter a unit rate"
    # with none of the price-chain account that branch appends, which is how we know it never
    # ran for them. Two lines with a rate sitting in config shipped at £0.00 on run after run,
    # and a zero on a quote is a free part.
    #
    # This function is the one place a purchased part is born — its own docstring says every
    # reader comes through here, which is why the manufacturer reference is captured here and
    # not in any of them. The same argument applies to a price we already hold: asked once,
    # here, and every reader gets the answer instead of four of them needing the same fix.
    #
    # LAST RESORT, NOT FIRST. Only a stub with no price of its own is touched, so a UDEF or
    # catalogue rate found by the caller still wins, and the pricing chain downstream can
    # still better it — a provisional is a floor, not a ceiling. Flagged, and it says whose
    # rate it is.
    # EXCEPT A COMMERCIAL LINE, WHICH THIS IMMEDIATELY GOT WRONG. PACKAGING and DELIVERY are
    # not bought-in components: they are per-order allowances owned by commercial_lines and
    # COMMERCIAL_LINE_GBP_PER_ORDER, which is HELD EMPTY BY DECISION until the estimators'
    # own figures land. The placeholder text reads "Packaging (box / pallet — per-unit
    # share)", the commodity table's PALLET entry matched the word "pallet" in it, and the
    # line came out at £12.00 — a figure nobody had agreed, on the one line the whole config
    # comment says must stay at an honest zero. A table of COMPONENT provisionals must never
    # answer for a commercial allowance.
    _cl_code = str(part_number or "").strip().upper()
    _cl_desc = str(description or "").upper()
    _is_commercial_line = (
        _cl_code in ("PACKAGING", "DELIVERY", "CARRIAGE", "FREIGHT")
        or "PER-UNIT SHARE" in _cl_desc
        or "ESTIMATOR TO PRICE" in _cl_desc
    )
    if _is_commercial_line:
        stub["_commercial_line"] = True
    if not _is_commercial_line and stub.get("unit_cost_gbp") in (None, 0, 0.0):
        try:
            from pricing_service import standard_commodity_price as _std_com
            _com = _std_com(stub)
        except Exception:                                        # noqa: BLE001
            _com = None
        try:
            _com_unit = float((_com or {}).get("unit_price_gbp") or 0)
        except (TypeError, ValueError):
            _com_unit = 0.0
        if _com_unit > 0:
            _q = _safe_int(quantity) or 1
            stub["unit_cost_gbp"] = round(_com_unit, 2)
            stub["unit_material_cost_gbp"] = round(_com_unit, 2)
            stub["extended_total_cost_gbp"] = round(_com_unit * _q, 2)
            stub["source"] = "standard_commodity_provisional"
            stub["cost_source"] = "standard_commodity_provisional"
            stub["price_verified"] = False
            stub["review_flags"].append(
                (_com or {}).get("review_reason")
                or "Provisional standard-commodity price — confirm against a supplier quote.")
            try:
                print(f"   [pricing] {part_number} ({str(description)[:40]}) priced from the "
                      f"standard commodity table at £{_com_unit:.2f} — "
                      f"{(_com or {}).get('price_source_note') or 'source not recorded'}",
                      flush=True)
            except Exception:                                    # noqa: BLE001
                pass

    return _supplier_reference.attach_references(stub)


def _lookup_udef_exact_code(code: str) -> Optional[Dict[str, Any]]:
    """Look up a single SDI part code (e.g. FIXING125, VINYL76) in the UDEF catalogue by
    EXACT code match. Returns {description, unit_price_gbp, supplier} or None.

    Exact match only — NEVER LIKE. A loose LIKE '%FIXING2%' matches FIXING236, FIXING2538,
    FIXING2658 (a £15 hinge) etc., which would attach a wildly wrong price to a cable tie.
    Exact-code is the safe path: the code on the drawing IS the catalogue key.
    """
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        cur.execute(
            "SELECT TOP 1 [Part code],[Description],[System cost per],[Supplier name] "
            "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
            "WHERE [Part code] = ? AND [System cost per] > 0",
            code.strip().upper(),
        )
        row = cur.fetchone()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass
    if not row:
        return None
    return {
        "code": str(row[0] or "").strip(),
        "description": str(row[1] or "").strip(),
        "unit_price_gbp": float(row[2]) if row[2] is not None else None,
        "supplier": str(row[3] or "").strip() or None,
    }


# A real SDI code binds the digits TIGHTLY to the prefix: FIXING125 / FIXING 125 / FIXING-125.
# It must NOT match the prefix word followed by an unrelated dimension (e.g. "NO VINYL 535.2 EXT"
# on a drawing) — that produced false positives VINYL535/VINYL497 from page-9 dimension noise.
# Rules: at most ONE space/hyphen between prefix and digits; digits NOT followed by a decimal
# point or a dimension/unit token (EXT, CRS, INT, MM, PITCH, THRU, DIA, R) which mark a measurement.
_SDI_BOUGHT_IN_CODE_RE = re.compile(
    r"\b(FIXING|VINYL|PRINT|SUBPLAS|POWDER)[ \-]?(\d{1,5})\b(?![.\d])"
    r"(?!\s*(?:EXT|CRS|INT|MM|PITCH|THRU|DIA|R\b|W\b|H\b|X\b))",
    re.IGNORECASE,
)

# A logo/vinyl callout in drawing prose, e.g. "MILWAUKEE LOGO WHITE 425 W X 190 H".
# Captures the W×H dimensions so we can match to a UDEF vinyl SKU by dimension (the only
# discriminator distinctive enough to price safely — a bare "vinyl" matches dozens of SKUs).
_VINYL_CALLOUT_RE = re.compile(
    r"(LOGO|VINYL|GRAPHIC)[^\n]{0,80}?(\d{2,4})\s*(?:W|WIDE|MM\s*W)?\s*[xX×]\s*(\d{2,4})\s*(?:H|HIGH|MM\s*H)?",
    re.IGNORECASE,
)


def _lookup_udef_vinyl_by_dimensions(w_mm: int, h_mm: int) -> Optional[Dict[str, Any]]:
    """Match a vinyl/logo callout to a UDEF vinyl SKU by its stated W×H dimensions.

    Prices ONLY when the dimensions resolve to exactly ONE priced vinyl SKU — dimensions are
    the safe discriminator (e.g. '425 x 190' uniquely identifies VINYL76). If 0 or >1 priced
    SKUs match, returns a 'flag' verdict (estimator to price) rather than guess among them.
    """
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        # Search both dimension orderings (425x190 / 190x425) within vinyl-ish rows.
        like_a = f"%{w_mm}%{h_mm}%"
        like_b = f"%{h_mm}%{w_mm}%"
        cur.execute(
            "SELECT [Part code],[Description],[System cost per],[Supplier name] "
            "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
            "WHERE [System cost per] > 0 "
            "AND ([Part code] LIKE 'VINYL%' OR [Description] LIKE '%VINYL%') "
            "AND ([Description] LIKE ? OR [Description] LIKE ?)",
            like_a, like_b,
        )
        rows = cur.fetchall()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass
    priced = [r for r in rows if r[2] is not None and float(r[2]) > 0]
    if len(priced) == 1:
        r = priced[0]
        return {"verdict": "priced", "code": str(r[0] or "").strip(),
                "description": str(r[1] or "").strip(),
                "unit_price_gbp": float(r[2]), "supplier": str(r[3] or "").strip() or None}
    # 0 or many -> ambiguous: recognise but do NOT price (honest flag, never guess among many).
    return {"verdict": "flag", "candidate_count": len(priced)}



# ---------------------------------------------------------------------------
# JOB-IDENTITY GUARD  (added after job 1310: a £105 phantom "Drill Stud Holder")
#
# The deterministic prose recogniser matches component head-words ("stud", "clip",
# "loom"...) against SDI quote history. On 1310 it read the PROJECT TITLE out of the
# title block — "DRILL STUD HOLDER" — matched it 1.0 against a historical quote line
# for that same finished product, and costed the job we are BUILDING as a part we BUY.
#
# The existing `_fab_descs` guard excludes fabricated PART descriptions (HOOK PLATE,
# STUD). It cannot catch this, because the assembly/product name is not a part.
#
# So: never recognise a bought-in whose description is made only of words that already
# name the job. "Drill Stud Holder" ⊂ {1310, DRILL, STUD, HOLDER, REV, C} -> dropped.
# A genuine purchased component is never named solely by the job's own title words.
# ---------------------------------------------------------------------------
_JOB_IDENT_STOPWORDS = {
    "REV", "REVISION", "DRAWING", "DRAWINGS", "ASSEMBLY", "GENERAL", "JSON", "PDF",
    "DXF", "AND", "THE", "FOR", "WITH", "OFF", "NEW", "OLD", "COPY", "FINAL",
}


def _job_identity_tokens(summary: Dict[str, Any]) -> set:
    """Words that name THIS job: job/file name, project title, drawing description."""
    import re as _re
    cands: List[str] = []
    for _k in ("job_name", "job", "source_file", "document_name", "file_name",
               "project_title", "drawing_title", "title", "description"):
        _v = summary.get(_k)
        if isinstance(_v, str) and _v.strip():
            cands.append(_v)
    _da = summary.get("document_analysis") or {}
    if isinstance(_da, dict):
        for _k in ("project_title", "drawing_title", "title", "job_title", "description"):
            _v = _da.get(_k)
            if isinstance(_v, str) and _v.strip():
                cands.append(_v)
    toks: set = set()
    for _c in cands:
        for _t in _re.findall(r"[A-Za-z]{3,}", _c.upper()):
            toks.add(_t)
    return toks - _JOB_IDENT_STOPWORDS


def _is_job_identity_desc(desc: Any, job_tokens: set) -> bool:
    """True when a candidate bought-in is named ONLY by the job's own title words."""
    import re as _re
    if not desc or not job_tokens:
        return False
    dt = set(_re.findall(r"[A-Za-z]{3,}", str(desc).upper())) - _JOB_IDENT_STOPWORDS
    if not dt:
        return False
    return dt.issubset(job_tokens)


def _graphic_part_matching_dims(existing_parts, w: int, h: int):
    """The job's own graphic/print part whose size is this callout's, or None.

    A GRAPHIC-SIZE callout describes a part the BOM usually already carries. On 10975-02
    the 297×210 callout minted VINYL-297X210 at a provisional £1.62 BESIDE 10975-02-G01 —
    the same A4 paper graphic, unpriced and waiting for the print rate — so the job showed
    the one artwork twice, once free and once guessed. When the BOM already owns the
    graphic, the callout belongs to that line, not to a sibling."""
    for p in existing_parts or []:
        if not isinstance(p, dict):
            continue
        text = f"{p.get('description') or ''} {p.get('part_number') or ''}".upper()
        mat = str(p.get("normalized_material") or p.get("material") or "").upper()
        if not ("GRAPHIC" in text or "PRINT" in text
                or mat in ("PAPER", "VINYL", "PRINTED")):
            continue
        pw = p.get("overall_length_mm") or p.get("overall_width_mm")
        dims = {round(float(p.get(k) or 0)) for k in
                ("overall_length_mm", "overall_width_mm", "overall_height_mm")}
        dims.discard(0)
        if not dims:
            return p        # a graphic with no stated size still owns its own callout
        if any(abs(d - w) <= 3 for d in dims) and any(abs(d - h) <= 3 for d in dims):
            return p
    return None


def _recognise_vinyl_callouts(all_text: str, existing_pns: set,
                              existing_descs: set,
                              existing_parts: Optional[List[Dict[str, Any]]] = None
                              ) -> List[Dict[str, Any]]:
    """Recognise logo/vinyl callouts in drawing prose and price by UNIQUE dimension match.

    Catches vinyl referenced by description (not code) — e.g. page-9 'MILWAUKEE LOGO WHITE
    425 W X 190 H' -> VINYL76 @ £0.85 (unique 425x190 match). Ambiguous callouts are added
    as flagged 'estimator to price' lines so the BOM line still appears without a guessed price.
    Generalises: any drawing's logo/vinyl callout with stated W×H is handled the same way.
    """
    found: List[Dict[str, Any]] = []
    seen_dims: set = set()
    for m in _VINYL_CALLOUT_RE.finditer(all_text):
        try:
            w = int(m.group(2)); h = int(m.group(3))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0 or (w, h) in seen_dims:
            continue
        # Plausibility: vinyl panels are tens-to-hundreds of mm, not microns or metres.
        if not (10 <= w <= 3000 and 10 <= h <= 3000):
            continue
        seen_dims.add((w, h))
        _owner = _graphic_part_matching_dims(existing_parts, w, h)
        if _owner is not None:
            _owner.setdefault("review_flags", []).append(
                f"graphic callout {w}x{h}mm matches this line — price the print here; "
                f"no separate vinyl/display-board line was minted for it")
            continue
        verdict = _lookup_udef_vinyl_by_dimensions(w, h)
        if not verdict:
            continue
        if verdict.get("verdict") == "priced":
            code = verdict["code"]
            if code.strip().upper() in existing_pns:
                continue
            stub = _bought_in_part_stub(code, verdict["description"] or code, 1)
            stub["unit_cost_gbp"] = verdict["unit_price_gbp"]
            stub["unit_material_cost_gbp"] = verdict["unit_price_gbp"]
            stub["extended_total_cost_gbp"] = round(verdict["unit_price_gbp"], 2)
            stub["source"] = "sdi_bom_code_udef_priced"   # reuse the price-preserving guard
            stub["cost_source"] = "udef_catalogue_vinyl_dimension_match"
            stub["supplier"] = verdict.get("supplier")
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"Vinyl matched by dimensions {w}x{h}mm -> {code} "
                f"(\u00a3{verdict['unit_price_gbp']:.2f}"
                + (f", {verdict['supplier']}" if verdict.get("supplier") else "") + ") — verify")
            found.append(stub)
        else:
            # Ambiguous (0 or many SKUs at these dims). These "GRAPHIC SIZE" callouts are typically
            # DISPLAY BOARD (printed foam/PVC substrate; artwork customer free-issue) — NOT vinyl.
            # Give a PROVISIONAL area-based price (documented placeholder, mirrors acrylic_sheet_
            # provisional) so the line carries a real number, flagged for the estimator to confirm
            # substrate + rate + in-house-vs-subcontract. Not a silent guess: the flag says PROVISIONAL.
            pn = f"VINYL-{w}X{h}"
            if pn in existing_pns:
                continue
            _DISPLAY_BOARD_PRICE_GBP_PER_M2 = 25.0   # provisional midpoint of £15–£40 printed board
            _area_m2 = (w / 1000.0) * (h / 1000.0)
            _prov_price = round(_area_m2 * _DISPLAY_BOARD_PRICE_GBP_PER_M2, 2)
            stub = _bought_in_part_stub(
                pn, f"DISPLAY BOARD {w}x{h}mm (PROVISIONAL @ £{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m²)", 1)
            stub["unit_cost_gbp"] = _prov_price
            stub["unit_material_cost_gbp"] = _prov_price
            stub["extended_total_cost_gbp"] = _prov_price
            stub["source"] = "sdi_bom_code_udef_priced"   # price-preserving guard (has a price now)
            stub["cost_source"] = "display_board_provisional_area"
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"DISPLAY BOARD {w}x{h}mm ({_area_m2:.3f} m²) priced PROVISIONALLY at "
                f"£{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m² = £{_prov_price:.2f} — "
                f"VERIFY substrate + rate; confirm in-house print vs sub-contract; artwork is "
                f"customer free-issue per drawing")
            found.append(stub)
    return found


def _recognise_sdi_coded_bought_in(
    all_text: str,
    existing_pns: set,
    bom_rows: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Find any FIXING/VINYL/etc coded line in the BOM text, price it from UDEF by EXACT code.

    This replaces reliance on the hard-coded `patterns` list for SDI-coded fixings & vinyl:
    those rows (e.g. FIXING125 M8 GLIDE, VINYL76 BASE PLATE) appear in the BOM table on every
    job but were silently skipped unless their exact code was pre-listed. General recognition
    + exact-code UDEF pricing catches them genuinely and generalises to all drawings.

    Quantity is read GENUINELY from the structured bom_rows quantity column when a matching row
    exists (Option B — not text-scraped, which is unreliable on flattened tables). When no
    structured qty is available, qty defaults to 1 and the line is flagged for the estimator to
    confirm — never a guessed multiple.
    """
    # Build a code -> quantity map from the STRUCTURED bom rows (genuine column, not text).
    _qty_by_code: Dict[str, int] = {}
    for _row in (bom_rows or []):
        _blob = f"{_row.get('part_number','')} {_row.get('description','')}"
        _cm = _SDI_BOUGHT_IN_CODE_RE.search(_blob)
        if not _cm:
            continue
        _rcode = f"{_cm.group(1).upper()}{_cm.group(2)}"
        _q = _safe_int(_row.get("quantity"))
        if _q and _q > 0:
            # If the same code appears on multiple BOM rows (e.g. per-sub-assembly), sum them.
            _qty_by_code[_rcode] = _qty_by_code.get(_rcode, 0) + _q

    found: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _SDI_BOUGHT_IN_CODE_RE.finditer(all_text):
        prefix = m.group(1).upper()
        digits = m.group(2)
        code = f"{prefix}{digits}"
        if code in seen or code in existing_pns:
            continue
        seen.add(code)
        _qty = _qty_by_code.get(code)            # genuine structured qty, or None
        _qty_known = _qty is not None and _qty > 0
        _use_qty = _qty if _qty_known else 1
        cat = _lookup_udef_exact_code(code)
        if cat and cat.get("unit_price_gbp") is not None:
            stub = _bought_in_part_stub(code, cat["description"] or code, _use_qty)
            # A record built on the line above, so this overwrites nothing — but a datum
            # with no source is invisible to arbitration, and a later pass would find an
            # unclaimed quantity it is free to replace.
            _apply_field(stub, "quantity", _use_qty, "bom_tree")
            stub["unit_cost_gbp"] = cat["unit_price_gbp"]
            stub["unit_material_cost_gbp"] = cat["unit_price_gbp"]
            stub["extended_total_cost_gbp"] = round(cat["unit_price_gbp"] * _use_qty, 2)
            stub["source"] = "sdi_bom_code_udef_priced"
            stub["cost_source"] = "udef_catalogue_exact_code"
            stub["supplier"] = cat.get("supplier")
            stub["price_verified"] = False
            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 (not in structured BOM) — estimator to confirm")

            # ── CONSUMABLES: never invent a quantity ─────────────────────────────────
            # For a DISCRETE item (rivet, junction box, light) "assume 1" is a defensible
            # default. For a CONSUMABLE sold by WEIGHT or VOLUME, "assume 1" means ONE
            # KILOGRAM — which is not a default, it is a fabricated number with a price on it.
            #
            # 7670: the drawing carries POWDER308 but no quantity. The engine priced 1kg at
            # £7.72 -> £8.03, to coat a wire frame with 0.023 m2 of surface. A kilo covers
            # ~6 m2. That is 300x more powder than the part can physically hold, and it became
            # the biggest line on a £6.74 job.
            #
            # Powder is ALSO costed by the workbook's own Powder Qty Calculator (AF82/AF83 ->
            # Total Material). A priced BOM line therefore risks DOUBLE-COUNTING on any job
            # with both sheet parts and a powder code in the drawing text. On 7670 that only
            # escaped because the calculator returns 0 for wire. Dropping the money from this
            # line closes that hazard too.
            #
            # Keep the ROW: the code and colour are real, drawing-derived and useful. Drop the
            # invented money and say plainly that the estimator must supply the quantity.
            # A STRIP IS NOT A ROLL, AND A KNOWN QUANTITY OF THE WRONG UNIT IS WORSE THAN AN
            # UNKNOWN ONE.
            #
            # 0355255's TAPE113C is supplied on a 10 METRE ROLL. The drawing asks for three
            # strips across the base — about 600 mm, six hundredths of a roll, 28p. The line
            # was costed 3 x the ROLL price: £13.63 against 28p, on a unit whose whole
            # manual estimate is £7.63. It is the entire gap between the two sheets, and it
            # does not amortise, which is why the AI column barely moves between 10 off and
            # 1000 off while the manual falls by a third.
            #
            # The guard below was written for exactly this and could not fire, twice over:
            # TAPE was not in the list, and the list only applies when the quantity is
            # UNKNOWN. Here the quantity is perfectly well known and is a count of PIECES
            # CUT FROM the pack, which is the one number that must never multiply a pack
            # price. So roll goods are withheld whether or not a count was read.
            _code_u = str(code or "").upper()
            _roll_goods = _code_u.startswith(("TAPE", "VINYL", "FOAM", "FELT", "REEL"))
            if (not _qty_known or _roll_goods) and any(
                _code_u.startswith(_cp)
                for _cp in ("POWDER", "PAINT", "LACQUER", "PRIMER",
                            "ADHESIVE", "SEALANT", "SOLVENT",
                            "TAPE", "VINYL", "FOAM", "FELT", "REEL")
            ):
                # Clear EVERY field that holds this price. The last attempt cleared two of
                # four and wb_populate's BOM fallback chain simply moved to the next one and
                # re-priced it at £7.72. One value living in four places is the root cause of
                # four separate bugs today; until that is fixed properly, unprice defensively.
                for _pk in ("unit_cost_gbp", "unit_material_cost_gbp", "cost_per_part_gbp",
                            "extended_total_cost_gbp", "extended_material_cost_gbp",
                            "unit_total_cost_gbp"):
                    stub[_pk] = None
                _me_c = stub.get("material_estimate")
                if isinstance(_me_c, dict):
                    for _pk in ("unit_material_cost_gbp", "cost_per_part_gbp",
                                "extended_material_cost_gbp"):
                        _me_c[_pk] = None
                    _me_c["cost_method"] = "consumable_qty_unknown_estimator_to_price"
                stub["source"] = "sdi_bom_code_unpriced"
                stub["cost_source"] = "consumable_qty_unknown_estimator_to_price"
                stub["_consumable_qty_unknown"] = True
                # The explicit marker. wb_populate must honour this and NOT go hunting for a
                # price in some other field. "Not priced" is a DECISION, not a missing value.
                stub["_price_explicitly_withheld"] = True
                # Keep the catalogue RATE (£/kg) even though the price is withheld. We
                # withheld because we could not know the QUANTITY — not because the rate is
                # unknown. If geometry can later supply a quantity (a wire frame's coated
                # area is real, computable, and invisible to the sheet-only powder
                # calculator), the reason for withholding evaporates and we can cost it.
                try:
                    stub["_catalogue_rate_gbp"] = float(cat["unit_price_gbp"])
                except Exception:
                    pass
                if _roll_goods:
                    # SAY THE ARITHMETIC, so confirming it is one line rather than a
                    # calculation. The estimator already does this sum in his head; what he
                    # cannot do is see that the sheet did a different one.
                    stub.setdefault("review_flags", []).append(
                        f"ROLL GOODS {code}: NOT PRICED, and NOT charged as "
                        f"{_use_qty} x £{cat['unit_price_gbp']:.2f} = "
                        f"£{cat['unit_price_gbp'] * _use_qty:.2f}. This is sold by the roll "
                        f"and the drawing asks for pieces CUT FROM one — a piece count must "
                        f"never multiply a pack price. Give the strip count and length and "
                        f"it prices as (length used ÷ roll length) × "
                        f"£{cat['unit_price_gbp']:.2f}"
                        + (f", {cat['supplier']}" if cat.get("supplier") else "")
                        + ". On 0355255 that was 3 x 200 mm = 600 mm of a 10 m roll = 0.06 "
                          "of a roll, about 28p — against £13.63 costed, on a £7.63 unit."
                    )
                else:
                    stub.setdefault("review_flags", []).append(
                        f"CONSUMABLE {code}: NOT PRICED. The quantity is not on the drawing, "
                        f"and a consumable is sold by weight/volume — defaulting to 1 would "
                        f"mean 1kg (that is how this line reached £8.03 on a £6.74 job). "
                        f"Estimator to supply the quantity. Catalogue rate "
                        f"£{cat['unit_price_gbp']:.2f}/unit"
                        + (f", {cat['supplier']}" if cat.get("supplier") else "")
                        + ". NOTE: powder is also computed by the workbook's Powder Qty "
                          "Calculator, which only understands SHEET area — wire/tube parts "
                          "contribute nothing, so a wire job gets zero powder until that is "
                          "fixed."
                    )
            stub.setdefault("review_flags", []).append(
                f"BOM-code bought-in: {code} priced from UDEF catalogue "
                f"(\u00a3{cat['unit_price_gbp']:.2f}"
                + (f", {cat['supplier']}" if cat.get("supplier") else "")
                + f"); {_qnote}")
        else:
            # Recognised the code but it's not priced in UDEF — honest flag, never guess.
            stub = _bought_in_part_stub(code, code, _use_qty)
            _apply_field(stub, "quantity", _use_qty, "bom_tree")
            stub["unit_cost_gbp"] = None
            stub["extended_total_cost_gbp"] = None
            stub["source"] = "sdi_bom_code_unpriced"
            stub["cost_source"] = "estimator_to_price"
            stub["price_verified"] = False
            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 — estimator to confirm")
            stub.setdefault("review_flags", []).append(
                f"BOM-code bought-in: {code} recognised but not found in UDEF catalogue "
                f"— estimator to price; {_qnote}")
        found.append(stub)
    return found


def extract_bought_in_from_pages(
    summary: Dict[str, Any],
    *,
    existing_part_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Scan assembly/BOM text for bought-in items that are not detail parts."""
    pages = summary.get("pages", [])
    if existing_part_records is not None:
        existing_parts = existing_part_records
    else:
        existing_parts = summary.get("manufacturing_writeup", {}).get("parts") or summary.get("parts") or []
    existing_pns = {str(p.get("part_number", "")).strip().upper() for p in existing_parts if p.get("part_number")}

    primary = " ".join(
        str(page.get("pdfplumber_text", "") or "") + " " + str(page.get("normalized_text", "") or "") for page in pages
    )
    secondary = " ".join(_page_text_for_bought_in_scan(p) for p in pages)
    all_text = (primary + " " + secondary).upper()

    patterns: List[Tuple[str, str, str, int]] = [
        (r"(\d+)?\s*(SHFP28|UKPOS[:.\s-]*SHFP28)", "SHFP28", "Pusher and Guide Rail 28mm", 4),
        (r"(\d+)?\s*(MAGNET23)", "MAGNET23", "Magnet 20mm DIA x 5mm", 6),
        (r"(\d+)?\s*(DBR39|VKF[:.\s-]*DBR39)", "VKF DBR39", "39mm Scanner Profile 280mm", 2),
        (r"(\d+)?\s*(DBR18|VKF[:.\s-]*DBR18)", "VKF DBR18", "18mm Scanner Profile 280mm", 2),
        (r"(\d+)?\s*(FIXING1784|RUBUSECSTRIP)", "FIXING1784", "Edging Seal Rubusecstrip 10m", 1),
        (r"(\d+)?\s*(FIXING47|NUTSERT\s*M4|M4\s+THIN\s+SHEET)", "FIXING47", "M4 Thin Sheet Nutsert", 6),
        (r"(\d+)?\s*(FIXING1067|BOLT\s*M4|M4\s*x\s*20)", "FIXING1067", "M4 x 20mm C/Snk Bolt", 6),
        (r"(\d+)?\s*(PALLET1|PALLET\b)", "PALLET1", "Pallet", 1),
        (r"(\d+)?\s*(BOX[- ]?296\s*[xX×]\s*404\s*[xX×]\s*40|BOX-296x404x40)", "BOX-296x404x40", "Box 296w x 404d x 40h", 1),
    ]

    bought_in: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()

    for regex, code, desc, default_qty in patterns:
        pn_key = code.strip().upper()
        if pn_key in existing_pns or code in seen_codes:
            continue
        matches = re.findall(regex, all_text, flags=re.IGNORECASE)
        if not matches:
            continue
        seen_codes.add(code)

        qty = default_qty
        first = matches[0]
        if isinstance(first, tuple):
            lead = first[0] if first else ""
            if lead and str(lead).strip().isdigit():
                qty = int(str(lead).strip())

        bought_in.append(_bought_in_part_stub(code, desc, qty))

    # General SDI-coded bought-in recognition (FIXING/VINYL/PRINT/SUBPLAS/POWDER by exact UDEF
    # code). Runs AFTER the hard-coded patterns and dedups against both existing parts and the
    # codes the patterns already produced, so nothing is double-counted. This is what catches
    # the per-job fixings & vinyl (FIXING125, VINYL76, ...) generically, no enumeration needed.
    _already = set(existing_pns) | {str(b.get("part_number", "")).strip().upper() for b in bought_in}
    _bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
    _coded = _recognise_sdi_coded_bought_in(all_text, _already, bom_rows=_bom_rows)
    if _coded:
        bought_in.extend(_coded)
        print(f"[DEBUG] SDI-coded bought-in recognised: {len(_coded)} -> "
              f"{[b['part_number'] for b in _coded]}")

    # Vinyl/logo callouts referenced by DESCRIPTION (not code), priced by unique dimension match
    # or flagged when ambiguous. Dedup against everything found so far.
    _already2 = set(existing_pns) | {str(b.get("part_number", "")).strip().upper() for b in bought_in}
    _existing_descs = {str(p.get("description", "")).strip().upper()
                       for p in existing_parts if p.get("description")}
    _vinyl = _recognise_vinyl_callouts(all_text, _already2, _existing_descs,
                                       existing_parts=existing_parts)
    if _vinyl:
        bought_in.extend(_vinyl)
        print(f"[DEBUG] Vinyl/logo callouts recognised: {len(_vinyl)} -> "
              f"{[b['part_number'] for b in _vinyl]}")

    if bought_in:
        print(f"[DEBUG] Bought-in items merged: {len(bought_in)} -> {[b['part_number'] for b in bought_in]}")

    return bought_in


def extract_bought_in_items_from_assembly(
    summary: Dict[str, Any],
    *,
    existing_part_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Alias for callers that name the scan by assembly page text (same as extract_bought_in_from_pages)."""
    return extract_bought_in_from_pages(summary, existing_part_records=existing_part_records)


def _merge_sheet_into_estimate_workbook_inputs(out_doc: Dict[str, Any], summary: Optional[Dict[str, Any]]) -> None:
    """Overlay qty and manual rates from the Estimate sheet when a workbook path is available."""
    ewb = out_doc.get("estimate_workbook_inputs")
    if not isinstance(ewb, dict):
        return
    candidates: List[Path] = []
    if summary:
        for key in ("estimate_workbook_path", "paired_estimate_workbook", "primary_spreadsheet_path"):
            raw = summary.get(key)
            if raw:
                candidates.append(Path(str(raw)))
    ss = (getattr(config, "PRICE_SOURCE_CONFIG", {}) or {}).get("spreadsheet", {}) or {}
    tb = ss.get("template_workbook")
    if tb:
        candidates.append(Path(str(tb)))
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        try:
            from estimate_sheet_discovery import read_estimate_workbook_inputs

            scan = read_estimate_workbook_inputs(path)
        except Exception as exc:
            ewb["sheet_scan_error"] = str(exc)
            return
        ewb["sheet_scan"] = scan
        if not scan.get("ok"):
            return
        # A DISCOVERED SHEET IS NOT AUTHORITY ON THIS RUN'S ORDER QUANTITY. The other values
        # here are shop constants — wire and steel per tonne, scrap — and a real sheet is a
        # better source for them than a config default. How many units THIS order is for is
        # not a constant: it is the number the customer stated and the number every part's
        # setup was amortised over. A manual estimate found for comparison, quite possibly
        # for a different batch, must not silently restate it.
        if (scan.get("assumed_job_quantity") is not None
                and ewb.get("assumed_job_quantity_source") != "job"):
            ewb["assumed_job_quantity"] = scan["assumed_job_quantity"]
            ewb["assumed_job_quantity_source"] = "discovered_sheet"
        if scan.get("wire_cost_per_tonne_gbp") is not None:
            ewb["wire_cost_per_tonne_gbp"] = scan["wire_cost_per_tonne_gbp"]
        if scan.get("sheet_steel_cost_per_tonne_gbp") is not None:
            ewb["sheet_steel_cost_per_tonne_gbp"] = scan["sheet_steel_cost_per_tonne_gbp"]
        return


# Source authority ranking for reconciliation: when two layers find the SAME physical item
# under different identifiers, the most-grounded source wins. Higher = more authoritative.
_BOUGHT_IN_SOURCE_RANK = {
    "sdi_bom_code_udef_priced": 5,        # exact UDEF catalogue code — most grounded
    "udef_catalogue_section": 5,
    "non_sdi_bom_row": 4,                 # a structured BOM-table row
    "sdi_bom_row_no_geometry": 4,
    "prose_recogniser_layer2": 3,         # deterministic prose match to SDI history
    "sdi_bom_code_unpriced": 2,           # recognised, flagged for pricing
    "llm_note_scan": 1,                   # LLM-found from prose — least grounded price
    "commercial_placeholder": 0,          # packaging/delivery — never dedup-dropped
}

_BI_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "for", "with", "mm", "black", "white", "x",
    "lighting", "loose", "all", "be", "used", "secure", "cm", "m", "no", "ref",
}


def _bought_in_token_set(part: Dict[str, Any]) -> Optional[set]:
    """Distinctive content tokens for a bought-in line (head nouns + numbers), for overlap
    dedup. Returns None when too little to compare on (then we never dedup — a possible
    duplicate is safer than a wrong merge).
    """
    desc = str(part.get("description") or "").upper()
    if not desc.strip():
        return None
    import re as _re
    toks = _re.findall(r"[A-Z]+|\d+(?:\.\d+)?", desc)
    keep = {t for t in toks if t.lower() not in _BI_STOPWORDS and len(t) > 1}
    # Stem words to 6 chars so ELECTRICS/ELECTRIC etc. align; keep numbers as-is.
    stemmed = {(t[:6] if not t.replace(".", "").isdigit() else t) for t in keep}
    words = {t for t in stemmed if not t.replace(".", "").isdigit()}
    if not words:
        return None
    return stemmed


def _bought_in_same_item(a: set, b: set) -> bool:
    """Two bought-in lines describe the same physical item if their distinctive WORD tokens
    overlap strongly AND any numbers present are consistent. Containment counts: the shorter
    description's words being a subset of the longer's is a match (e.g. {LOOM,50} ⊂
    {ELECTR,LOOM,50}; {DOME,RIVET} ⊂ {DOME,FIXING,RIVET,10,4.0}).
    """
    aw = {t for t in a if not t.replace(".", "").isdigit()}
    bw = {t for t in b if not t.replace(".", "").isdigit()}
    an = {t for t in a if t.replace(".", "").isdigit()}
    bn = {t for t in b if t.replace(".", "").isdigit()}
    if not aw or not bw:
        return False
    shared_w = aw & bw
    smaller_w = min(len(aw), len(bw))
    # Word side: the smaller description's words must be (almost) wholly contained in the other.
    if smaller_w == 0:
        return False
    word_contained = len(shared_w) >= max(1, smaller_w)  # full containment of the smaller set
    if not word_contained:
        # allow one-word slack on larger sets (e.g. 3-word vs 3-word sharing 2)
        if smaller_w >= 3 and len(shared_w) >= smaller_w - 1:
            word_contained = True
    if not word_contained:
        return False
    # Number side: if BOTH carry numbers, they must share at least one (don't merge a 50cm
    # loom with a 100cm loom). If only one side has numbers, the contained-word match stands.
    if an and bn and not (an & bn):
        return False
    return True


def _reconcile_bought_in(parts: List[Dict[str, Any]], *, all_text: str = "", debug: bool = False) -> List[Dict[str, Any]]:
    """Collapse cross-layer duplicate bought-in lines, keeping the most-grounded source.

    Same-identifier dupes are already prevented upstream by existing_pns guards. THIS pass
    catches the harder case: the same physical item found by two DIFFERENT layers under
    different part numbers (BOM-table loom vs note-scan loom; FIXING5 vs BI-DOMERIVET). Lines
    whose distinctive tokens overlap (containment) are merged — the higher-authority source is
    kept, the duplicate dropped, and the survivor flagged so the merge is auditable, never
    silent. Fabricated parts and commercial placeholders are never dedup-dropped.
    """
    def _is_fabricated_part(p: Dict[str, Any]) -> bool:
        # A part with its own flat-pattern DXF (or a real SDI part number + geometry) is a
        # MANUFACTURED part, not a bought-in line — even if it also carries a 'bought_in'
        # page-role. Such parts must never be collapsed by the bought-in description dedup
        # (which caused distinct GRAPHIC CHANNEL parts to be merged by token overlap).
        _gs = str(p.get("geometry_source") or "").lower()
        if ("dxf" in _gs or p.get("dxf_augmented") or p.get("dxf_source_file")
                or _has_native_flat(p)):
            return True
        import re as _re
        _pn = str(p.get("part_number") or "").upper()
        if _re.match(r"^\d{4,5}-\d{2}-\d{2,3}[A-Z]?$", _pn) and (
            p.get("blank_length_mm") or p.get("overall_length_mm")
            or (p.get("dxf_raw_geometry") or {}).get("blank_area_mm2")
        ):
            return True
        return False

    def _is_bought_in(p: Dict[str, Any]) -> bool:
        if _is_fabricated_part(p):
            return False
        roles = p.get("page_roles") or []
        return "bought_in" in roles or str(p.get("source") or "") in _BOUGHT_IN_SOURCE_RANK

    keep: List[Dict[str, Any]] = []
    kept_tokens: List[Tuple[int, set]] = []   # (index in keep, token set) for bought-in lines
    dropped = 0
    for p in parts:
        if not _is_bought_in(p) or p.get("_commercial_placeholder"):
            keep.append(p)
            continue
        toks = _bought_in_token_set(p)
        match_idx = None
        if toks is not None:
            for idx_in_keep, ktoks in kept_tokens:
                if _bought_in_same_item(toks, ktoks):
                    match_idx = idx_in_keep
                    break
        # Guard: never merge two lines that carry DIFFERENT, non-empty part numbers. Distinct
        # part numbers = distinct items (e.g. VINYL-668X200 vs VINYL-668X1264 are different display
        # boards that only *look* similar because their descriptions share words + the spurious "25"
        # from "£25/m²"). The token-overlap merge is meant for the SAME item found under different
        # numbers by different layers, not for genuinely distinct catalogue lines.
        if match_idx is not None:
            _pn_new = str(p.get("part_number") or "").strip().upper()
            _pn_old = str(keep[match_idx].get("part_number") or "").strip().upper()
            if _pn_new and _pn_old and _pn_new != _pn_old:
                # Cancel the merge only when the two codes are genuinely DISTINCT catalogue
                # lines, not the same physical item found by two layers under different
                # identifiers. Distinct = same alphabetic family differing in detail
                # (VINYL-668X200 vs VINYL-668X1264 — real different boards), OR both
                # numeric-style SDI codes. DIFFERENT identifier schemes for one item
                # (ELECTRICS 50CM vs BI-50CMLOOM — a described BOM commodity vs its
                # catalogue code) SHOULD still merge: that is the cross-layer duplicate
                # this pass exists to catch.
                import re as _re_fam
                _fam_new = (_re_fam.match(r"[A-Za-z]+", _pn_new) or [None])
                _fam_new = _fam_new.group(0) if hasattr(_fam_new, "group") else ""
                _fam_old = (_re_fam.match(r"[A-Za-z]+", _pn_old) or [None])
                _fam_old = _fam_old.group(0) if hasattr(_fam_old, "group") else ""
                _same_family = bool(_fam_new and _fam_old and _fam_new == _fam_old)
                _both_numeric = (not _fam_new) and (not _fam_old)
                if _same_family or _both_numeric:
                    match_idx = None
        if match_idx is None:
            if toks is not None:
                kept_tokens.append((len(keep), toks))
            keep.append(p)
            continue
        # Duplicate of an already-kept bought-in line — keep the more-grounded source.
        existing = keep[match_idx]
        rank_new = _BOUGHT_IN_SOURCE_RANK.get(str(p.get("source") or ""), 0)
        rank_old = _BOUGHT_IN_SOURCE_RANK.get(str(existing.get("source") or ""), 0)
        winner, loser = (p, existing) if rank_new > rank_old else (existing, p)

        # A CLASS WORD MUST NOT WIN AN IDENTITY IT CANNOT BE LOOKED UP BY.
        #
        # The rank decides which SOURCE is better grounded, and says nothing about which of
        # the two records can actually be priced. On 12349-02 the engine held both spellings
        # of the same three items and kept the wrong half of each pair:
        #
        #     BOM row 18   STD PART   3.5x19mm WOOD SCREW               £0.00
        #     AI Material  BI-SCREW   3.5x19mm WOOD SCREW
        #     BOM row 19   FIXING     M4x10mm FLANGE BUTTON HEAD SCREW  £0.00
        #     AI Material  BI-BUTTONSCREW  M4x10mm FLANGE BUTTON HEAD SCREW
        #
        # So it is not that the drawing prints no code — we RESOLVED one and then dropped it
        # in favour of the word the drawing prints where a code would go. Nothing downstream
        # can price "FIXING", and every later layer that tries reports an honest miss against
        # an identity that was never lookupable.
        #
        # Asked after rank and only when the two disagree about this, so a better-grounded
        # source still wins on its own merits everywhere else.
        try:
            from part_code_conventions import is_category_not_a_code as _is_class
            _w_class = _is_class(str(winner.get("part_number") or ""))
            _l_class = _is_class(str(loser.get("part_number") or ""))
            if _w_class and not _l_class:
                winner, loser = loser, winner
                winner.setdefault("review_flags", []).append(
                    f"Kept '{winner.get('part_number')}' over '{loser.get('part_number')}': "
                    f"the other spelling is a CLASS word the drawing prints where an item "
                    f"has no code, and nothing can look a rate up against it")
        except Exception:                                        # noqa: BLE001
            pass
        winner.setdefault("review_flags", []).append(
            f"Reconciled: same item also found as '{loser.get('part_number')}' "
            f"({loser.get('source')}) — kept '{winner.get('part_number')}' "
            f"({winner.get('source')}, more grounded), dropped the duplicate")
        keep[match_idx] = winner
        # refresh the token set for the winner at that slot
        kept_tokens = [(i, (_bought_in_token_set(winner) if i == match_idx else t)) for (i, t) in kept_tokens]
        dropped += 1
    if dropped and debug:
        print(f"[DEBUG] Bought-in reconciliation: dropped {dropped} cross-layer duplicate(s)")
    if dropped:
        print(f"   [reconcile] {dropped} duplicate bought-in line(s) merged (kept most-grounded source)")
    return keep


# ── ALWAYS A NUMBER: a real line is never left reading as free ──────────────────────────────
def _last_resort_price_is_needed(pe: Dict[str, Any]) -> bool:
    """Is this a REAL line that ended with no money at all — 'reads as free' — and may take a
    last-resort market price? Refuses every line that is £0 for a reason.

    A blank in the money column reads as a part that is free to make. Where the engine simply
    could not find a price for a real bought-in, the honest answer is an indicative market
    figure (non-firm), not a blank — the estimator can strike a number they can see and never
    a zero they miss. A possible-double-count line is NOT excluded here: the mandate is a price
    on every line, and that line already carries a loud 'confirm/strike' flag, so it takes a
    figure like any other. Only a line that is £0 ON PURPOSE is left alone."""
    # Placeholders (packaging/delivery) and customer-supplied lines are £0 by design.
    if pe.get("_commercial_placeholder") or str(pe.get("source") or "") == "commercial_placeholder":
        return False
    _rf = " ".join(str(f) for f in (pe.get("risk_flags") or []))
    if "customer_supplied_zero_cost" in _rf:
        return False
    # An assembly parent carries its material on its children; its own £0 is correct.
    if pe.get("is_assembly_parent") or (pe.get("route_context") or {}).get("is_assembly_parent"):
        return False
    # A firm catalogue price already reached this line through the bought-in path; the
    # money is in the line total by design and there is nothing to look up again.
    if str(pe.get("costing_basis") or "") == "system_cost_per_part":
        return False
    if ((pe.get("cost_breakdown") or {}).get("system_cost") or {}).get("applied_to_total"):
        return False

    # THE MATERIAL COLUMN IS WHAT SETTLES THIS, NOT THE LINE TOTAL.
    #
    # This asked `extended_total_cost_gbp`, which is material PLUS labour (see the
    # computed branch of estimate_part). Every fixing carries a couple of minutes of
    # handling, so every fixing had a line total, so no fixing was ever rescued — and
    # its material cell stayed blank. That is the £0 hardware on 12349's BOM: screws,
    # inserts, glides and the acrylic/MDF panels all read as free in the one column an
    # estimator looks at for a price, while the rescue that exists to prevent exactly
    # that sat behind a test they could not fail.
    #
    # Ask the column the blank appears in — WHERE THERE IS ONE. A line carrying money and no
    # material record at all is a different animal: nothing says what its total is made of, so
    # re-pricing it could only double-apply. Those keep the original test.
    _me = pe.get("material_estimate")
    if isinstance(_me, dict) and _me:
        _material_on_the_line = (
            (_safe_float(_me.get("extended_material_cost_gbp")) or 0.0)
            or (_safe_float(_me.get("unit_material_cost_gbp")) or 0.0)
            or (_safe_float(_me.get("cost_per_part_gbp")) or 0.0)
        )
        if _material_on_the_line > 0:
            return False
    elif (_safe_float(pe.get("extended_total_cost_gbp")) or 0.0) > 0:
        return False
    # Nothing to look a price up against.
    if not str(pe.get("description") or pe.get("part_number") or "").strip():
        return False
    return True


def apply_last_resort_prices(part_estimates: List[Dict[str, Any]],
                             price_lookup) -> int:
    """Give every real 'reads as free' line a per-each market/LLM indicative that ENTERS the
    non-firm total. `price_lookup(pe)` returns a unit £ or None; None leaves the line an honest
    gap (a market figure is not invented where none exists). Never touches a sealed recogniser
    query. Returns how many lines it rescued."""
    n = 0
    for pe in part_estimates or []:
        if not isinstance(pe, dict) or not _last_resort_price_is_needed(pe):
            continue
        try:
            unit = _safe_float(price_lookup(pe))
        except Exception:                                        # noqa: BLE001
            unit = None
        if unit is None or unit <= 0:
            continue
        qty = _safe_int(pe.get("quantity")) or 1
        _unit = _round_money(unit)
        _ext = _round_money(unit * qty)
        # THE MATERIAL IS ADDED TO THE LINE, IT DOES NOT BECOME THE LINE.
        #
        # Now that a line with labour on it can be rescued, assigning the material price
        # to `extended_total_cost_gbp` would throw that labour away — a fixing with 2 min
        # of handling would go from £1.04 of labour to £0.40 all-in, and the rescue meant
        # to add a missing price would quietly subtract a real one. Both were zero before
        # this, which is why the assignment read as harmless.
        _prior_unit = _safe_float(pe.get("unit_total_cost_gbp")) or 0.0
        _prior_ext = _safe_float(pe.get("extended_total_cost_gbp")) or 0.0
        _me = pe.setdefault("material_estimate", {})
        _me.update({
            "unit_material_cost_gbp": _unit, "cost_per_part_gbp": _unit,
            "extended_material_cost_gbp": _ext,
            "cost_method": "last_resort_market_indication",
        })
        pe["unit_cost_gbp"] = _round_money(_prior_unit + _unit)
        pe["unit_total_cost_gbp"] = _round_money(_prior_unit + _unit)
        pe["extended_total_cost_gbp"] = _round_money(_prior_ext + _ext)
        pe["costing_basis"] = ("last_resort_market_indication_plus_labour"
                               if _prior_ext else "last_resort_market_indication")
        pe.setdefault("review_flags", []).append(
            "AI/MARKET LAST-RESORT PRICE: no catalogue/UDEF/derived price was found, so an "
            "indicative market figure is shown rather than a blank that reads as free. NON-FIRM "
            "— verify or replace with a supplier rate before quoting.")
        n += 1
    return n


def _last_resort_lookup(pe: Dict[str, Any]) -> Optional[float]:
    """The per-each price for a 'reads as free' line: the same UDEF/RAG/catalogue/LLM chain the
    system-cost path uses, run as a guaranteed last resort for a line the normal path left
    unpriced (a bought-in the classifier skipped, a code the first pass did not look up)."""
    try:
        return _safe_float(_resolve_part_system_cost(pe).get("applied_unit_cost"))
    except Exception:                                            # noqa: BLE001
        return None


def estimate_document(parts: List[Dict[str, Any]], summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    if summary is not None:
        bought_in_items = extract_bought_in_from_pages(summary, existing_part_records=parts)
        if bought_in_items:
            parts.extend(bought_in_items)
            if debug:
                print(f"[DEBUG] Bought-in items merged into estimate: {len(bought_in_items)} -> {[b.get('part_number') for b in bought_in_items]}")

        # Loose bought-in components in assembly-note PROSE (not BOM rows): e.g. the
        # header assembly page lists "JUNCTION BOX ... 5m MAINS CABLE ... EARTH STRAP
        # ... ADHESIVE CABLE CLIP ... FOAM TAPE" as fitting instructions, never as
        # table rows, so extract_bought_in_from_pages (BOM-row based) cannot see them.
        # scan_notes_for_bought_in reads the note text and surfaces these as flagged,
        # AI-identified lines (priced via the shared waterfall, "estimator to verify").
        # Additive + reconciled against what we already found — never double-counts the
        # loom/fixings already captured above. Gated behind NOTE_SCAN_POLICY.enable; a
        # no-op (returns []) if disabled, the LLM is unavailable, or nothing new is found.
        try:
            from note_scan import scan_notes_for_bought_in
            # Assemble the assembly-page note text the engine already extracted.
            _note_chunks: List[str] = []
            for _pg in summary.get("pages", []) or []:
                _role = (_pg.get("page_role") or {})
                _is_assembly = (
                    (isinstance(_role, dict) and _role.get("primary_role") == "assembly")
                    or _role == "assembly"
                )
                # Include assembly pages; their region_text.notes / full text carry the prose.
                if _is_assembly:
                    # GUARD 1 (job 1310): notes region first, then ONE page-text variant.
                    # Previously ALL FOUR text variants were appended — the recogniser was
                    # handed four copies of the whole page (title block included).
                    _rt = _pg.get("region_text") or {}
                    if isinstance(_rt, dict) and _rt.get("notes"):
                        _note_chunks.append(str(_rt["notes"]))
                    # GUARD-1 REVERTED 2026-07-13. The `break` here took only the FIRST text
                    # variant. These four keys are DIFFERENT extractions of the same page, not
                    # duplicates — pdfplumber_text is nearly always present, so the loop broke on
                    # it and normalized_text / pypdf_text / text_preview were never read. That
                    # deterministically lost BI-LEDDOWNLIGHTS (£26) from 1282 for three runs.
                    # _note_text feeds BOTH the prose recogniser AND the LLM note-scan, so
                    # starving it blinded both. Append every variant, as before.
                    # The £105 phantom stays fixed by GUARD 2 (_job_identity_tokens), which does
                    # not depend on this loop.
                    for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):
                        _v = _pg.get(_k)
                        if _v:
                            _note_chunks.append(str(_v))
            _note_text = "\n".join(_note_chunks)
            if _note_text.strip():
                _existing_pns = {str(p.get("part_number", "")).strip().upper() for p in parts if p.get("part_number")}
                _seen_codes = set(_existing_pns)
                _existing_descs = {str(p.get("description", "")).strip().upper() for p in parts if p.get("description")}
                # AN ASSEMBLY'S OWN BOM ROW IS ON THE BOM TOO. The part records hold what is
                # MADE or BOUGHT; a sub-assembly's row ("END PANEL GF CONVERSION PANEL SET
                # AC0706-05", 11650-06-SA01) is often not among them. So "end panel" in the
                # kit GA's text matched nothing, and a bought-in "End Panel" was minted and
                # priced at £943.42 — half the unit on the 11650-02 run of 23 Sep 2026. Every
                # BOM row and every assembly the extract names is part of what "already on the
                # BOM" means.
                _da_rows = ((summary.get("document_analysis") or {}) if isinstance(summary, dict)
                            else {})
                _bom_like = list(_da_rows.get("bom_rows") or []) + list(
                    _da_rows.get("bay_bom_rows") or [])
                _lfe = (summary.get("llm_full_extract") or {}) if isinstance(summary, dict) else {}
                for _asm in (_lfe.get("assemblies") or []):
                    if isinstance(_asm, dict):
                        _bom_like.append(_asm)
                        _bom_like.extend(c for c in (_asm.get("children") or [])
                                         if isinstance(c, dict))
                for _row in _bom_like:
                    if not isinstance(_row, dict):
                        continue
                    _rd = str(_row.get("description") or "").strip().upper()
                    _rp = str(_row.get("part_number") or "").strip().upper()
                    if _rd:
                        _existing_descs.add(_rd)
                    if _rp:
                        _existing_pns.add(_rp)

                # DETERMINISTIC-PRIMARY: run the deterministic prose recogniser FIRST.
                # It matches a vocabulary of bought-in component TYPES mined from SDI's own
                # history (clip/strap/tie/cable/loom...), prices confident matches from
                # historical quote lines, and guards against double-counting fabricated
                # parts (passed as fabricated_descriptions). Same input -> same output every
                # run (no LLM), so it protects parity. The LLM note-scan then only needs to
                # backstop genuinely-novel prose items the vocabulary doesn't yet know.
                # Degrades to [] if no DB / no vocab — the LLM backstop still carries.
                try:
                    from bought_in_recogniser import recognise_bought_in_in_prose
                    import config as _cfg_det
                    # Fabricated (made-in) part descriptions — so the recogniser never prices
                    # a part that's already counted as a DXF/sheet fabricated item.
                    _fab_descs = {
                        str(p.get("description", "")).strip().upper()
                        for p in parts
                        if p.get("description") and "bought_in" not in (p.get("page_roles") or [])
                    }
                    _det_items = recognise_bought_in_in_prose(
                        _note_text,
                        get_connection=_cfg_det.get_connection,
                        existing_pns=_existing_pns,
                        existing_descriptions=_existing_descs,
                        fabricated_descriptions=_fab_descs,
                        stub_builder=_bought_in_part_stub,
                        # The pages the notes above were read from, so a recognised purchase
                        # can say which sheet listed it. The join at _note_text is what the
                        # recogniser reads; this is only how it reports where a hit came
                        # from, so nothing about which phrases match changes.
                        pages=(summary.get("pages") or []),
                    )
                    # GUARD 2 (job 1310): never keep a bought-in that IS the job itself.
                    # The recogniser read the PROJECT TITLE from the title block, matched it
                    # 1.0 against a historical quote line for the same finished product, and
                    # costed it as a purchased part (£105 on a £6.90 job).
                    _job_toks = _job_identity_tokens(summary)
                    _kept_di, _dropped_di = [], []
                    for _di in (_det_items or []):
                        if _is_job_identity_desc(_di.get("description"), _job_toks):
                            _dropped_di.append(_di)
                        else:
                            _kept_di.append(_di)
                    for _dd in _dropped_di:
                        print("   [recogniser] DROPPED self-referential bought-in "
                              f"{_dd.get('description')!r} (£{_dd.get('unit_cost_gbp')}) — "
                              "its name is the JOB TITLE, not a purchased component.")
                    _det_items = _kept_di
                    
                    # GUARD 3: a recognised bought-in that carries a price it could not verify
                    # must SAY SO on the console. Previously confidence=0.0 / price_verified=False
                    # was recorded in JSON and silently ignored — £105 landed unannounced.
                    for _di in (_det_items or []):
                        _c = _di.get("unit_cost_gbp")
                        if _c and not _di.get("price_verified", False):
                            try:
                                _cf = float(_c)
                            except Exception:
                                continue
                            _lvl = "!! HIGH-VALUE" if _cf >= 25.0 else "!"
                            print(f"   [recogniser] {_lvl} UNVERIFIED price £{_cf:.2f} on "
                                  f"{_di.get('description')!r} "
                                  f"(source: {_di.get('source')}) — estimator to verify.")
                    
                    if _det_items:
                        parts.extend(_det_items)
                        # Feed deterministic finds into the dedup sets so the LLM backstop
                        # does not re-find the same items.
                        for _di in _det_items:
                            _pn = str(_di.get("part_number", "")).strip().upper()
                            if _pn:
                                _existing_pns.add(_pn); _seen_codes.add(_pn)
                            _dd = str(_di.get("description", "")).strip().upper()
                            if _dd:
                                _existing_descs.add(_dd)
                        print(f"   [recogniser] {len(_det_items)} bought-in item(s) deterministically "
                              f"recognised in notes: {[b.get('description') for b in _det_items]}")
                except Exception as _de:
                    if debug:
                        print(f"[DEBUG] deterministic recogniser skipped: {_de}")

                # LLM BACKSTOP: only finds what the deterministic layer missed (the dedup
                # sets above now include the deterministic finds).
                _note_items = scan_notes_for_bought_in(
                    _note_text,
                    existing_pns=_existing_pns,
                    seen_codes=_seen_codes,
                    existing_descriptions=_existing_descs,
                    stub_builder=_bought_in_part_stub,
                )
                if _note_items:
                    parts.extend(_note_items)
                    print(f"   [note-scan] {len(_note_items)} loose bought-in item(s) found in assembly notes: "
                          f"{[b.get('description') for b in _note_items]} (flagged for verification)")
        except Exception as _e:
            if debug:
                print(f"[DEBUG] note_scan skipped: {_e}")

        # Commercial lines that every quote carries but the DRAWINGS do not price:
        # packaging and delivery. Their real cost is order-specific (box size, pallet
        # count, destination, haulier) and lives in the enquiry, not the engineering —
        # the engine cannot genuinely derive a price from the drawings, so we add them
        # as ALWAYS-PRESENT, UNPRICED placeholder lines flagged for the estimator. This
        # makes the BOM complete (these lines are never silently omitted) without
        # inventing a number. Reconciled so they are not added twice if a re-estimate runs.
        _existing_now = {str(p.get("part_number", "")).strip().upper() for p in parts if p.get("part_number")}
        _dec_block = (summary or {}).get("estimator_decisions") or {}
        _excluded_cl = {str(c).strip().upper()
                        for c in (_dec_block.get("commercial_excluded") or [])}
        for _code, _desc in (
            ("PACKAGING", "Packaging (box / pallet — per-unit share, estimator to price)"),
            ("DELIVERY", "Delivery (per-unit share of order haulage — estimator to price)"),
        ):
            if _code in _existing_now:
                continue
            # AN ESTIMATOR'S "NOT REQUIRED" IS AN ANSWER, NOT A GAP. Tony: "Delivery is
            # not required" — and the line still went out as "estimator to price", an
            # open question on every run of a job whose answer was already given. An
            # excluded line stays ON the sheet at a deliberate £0 saying whose call it
            # was; absence would read as forgotten.
            if _code in _excluded_cl:
                _who_x = str(_dec_block.get("decided_by") or "the estimator")
                _stub = _bought_in_part_stub(
                    _code, f"{_code.capitalize()} — NOT REQUIRED for this job "
                           f"(excluded by {_who_x}; a decision, not a missing price)", 1)
                _stub["source"] = "commercial_placeholder"
                _stub["_commercial_excluded"] = True
                _stub["price_verified"] = True
                _stub["unit_cost_gbp"] = 0.0
                _stub["unit_material_cost_gbp"] = 0.0
                _stub["extended_total_cost_gbp"] = 0.0
                _stub.setdefault("review_flags", []).append(
                    f"{_code}: excluded by {_who_x} — not required for this job. The £0 "
                    f"is the decision, not a gap.")
                parts.append(_stub)
                print(f"   [commercial] {_code} EXCLUDED — {_who_x}'s decision: not "
                      f"required for this job", flush=True)
                continue
            # ASKED, NOT DERIVED — AND NOT LEFT AT ZERO. The comment above is right that the
            # engine cannot DERIVE these from the drawings, and wrong that it therefore has
            # nothing to say. It holds the assembly size, every blank, the gauges, the
            # densities and the order quantity: that is a describable shipment, and a
            # describable shipment is a question the market answers. A zero sums as free and
            # nobody argues with it; an indicative figure gets checked.
            try:
                import commercial_lines as _cl
                # HOW MANY OF THE ASSEMBLY THIS ORDER IS FOR — the one number both lines turn
                # on. file_scan stamps it onto summary['assumed_job_quantity'] (and 'quantity'),
                # which is where the rest of this function reads it; the old read looked under
                # summary['estimating_workbook'], a key nothing ever sets, so it fell to 1 and
                # divided EVERY order by one — 400-off packaging landed at GBP 115 a unit
                # instead of 29 pence.
                _oq = _commercial_order_quantity(summary)
                _cline = (_cl.packaging_line(parts, _oq) if _code == "PACKAGING"
                          else _cl.delivery_line(parts, _oq))
            except Exception as _cl_exc:                    # noqa: BLE001
                # THE ONE PATH WITH NO VOICE. A crash here used to land as a bare £0
                # wearing the ordinary estimator-to-price text — indistinguishable from a
                # deliberate withhold, which is how the 18:21 zero took a JSON grep to
                # diagnose. The line still fails soft; it just says so.
                print(f"   [packing] {_code} line could not be built "
                      f"({type(_cl_exc).__name__}: {_cl_exc}) — held at £0, estimator "
                      f"to price", flush=True)
                _cline = None
            _unit = (_cline or {}).get("unit_gbp")
            # A LINE AND A ZERO ON THE SHEET — NOT AN ESSAY. Packaging and delivery are the two
            # deliberate £0 order-lever lines; the estimator wants a clean row, not the
            # withheld-because-5.7x explanation baked into the BOM description. The full note is
            # kept on the commercial_line record below, where the covering note and quote read
            # it — the sheet line stays the short base label.
            _stub = _bought_in_part_stub(_code, _desc, 1)
            _stub["source"] = "commercial_placeholder"
            _stub["price_verified"] = False
            _stub["unit_cost_gbp"] = float(_unit or 0.0)
            _stub["unit_material_cost_gbp"] = float(_unit or 0.0)
            _stub["extended_total_cost_gbp"] = float(_unit or 0.0)
            # WHERE THE FIGURE CAME FROM decides how the line reads. A config house hold
            # (config.COMMERCIAL_LINE_GBP_PER_ORDER) is an INDICATIVE per-order rate an
            # estimator entered — priced and reproducible, but flagged for Tim to verify, not a
            # firm catalogue price and not a market guess. Absent a hold, the line stays the
            # honest £0 "estimator to price".
            _cl_src = ((_cline or {}).get("price_source") or {})
            _from_hold = bool(_cl_src.get("source_class") == "config_house_rate")
            _from_method = bool(_cl_src.get("source_class") == "packing_method")
            _stub["cost_source"] = ("config_commercial_indicative" if _from_hold
                                    else ("stated_method_system_priced" if _from_method
                                          else ("market_indication" if _unit
                                                else "estimator_to_price")))
            if _from_method:
                # "when we explain the packaging and delivery on s/sheet we need to try to
                # provide as much clarity as possible on the number" — James, 15 Sep. The
                # ROW says what the number is made of; the full arithmetic is one flag away.
                # The codes come from the method itself, so the row can never name a bag
                # the method no longer buys — Howard's sheet moved PACK13 to PACK56 and
                # a literal here would have kept printing the old one.
                _pm_cons = (getattr(config, "PACKING_METHOD", {}) or {}).get(
                    "consumables") or []
                _bag_code = next((str(c.get("code")) for c in _pm_cons
                                  if isinstance(c, dict) and c.get("per_unit")), "bag")
                _box_code = next((str(c.get("code")) for c in _pm_cons
                                  if isinstance(c, dict) and c.get("per_order_steps")),
                                 "box")
                _stub["description"] = (f"Packaging — bagged ({_bag_code}) + boxed "
                                        f"({_box_code}), Howard's stated method, priced "
                                        f"from SDI Live")
            if _cline:
                _stub["commercial_line"] = _cline
                _announce_packing_status(_cline)
            # No operations — these are pure commercial placeholders, not fabricated/handled
            # parts, so they must not accrue handling labour. Keep them genuinely £0.
            _stub["textual_operations"] = []
            _stub["inferred_operations"] = []
            _stub["_commercial_placeholder"] = True
            _stub["review_flag"] = True
            _stub["review_flags"] = [
                (f"INDICATIVE house rate £{float(_unit):.2f}/unit from "
                 f"config.COMMERCIAL_LINE_GBP_PER_ORDER — verify before quoting (packaging "
                 f"size / pallet count / destination).") if _from_hold and _unit else
                (f"PACKED BY THE STATED METHOD ({(_cline or {}).get('method_source')}): "
                 f"{(_cline or {}).get('packing_working')} — counts stated, prices live "
                 f"from the system this run; confirm the method fits this job before "
                 f"quoting.") if _from_method and _unit else
                (f"Commercial line — estimator to price. Packing method: "
                 f"{(_cline or {}).get('method_status')}.")
                if (_cline or {}).get("method_status") else
                "Commercial line — not derivable from drawings; estimator to price "
                "(order-specific: packaging size / pallet count / destination)."
            ]
            parts.append(_stub)
        if debug:
            print("[DEBUG] Added Packaging + Delivery placeholder lines (unpriced, flagged)")

        # ── ABS EDGING: A MATERIAL LINE, NOT A QUESTION ───────────────────────────────
        #
        # Tony Ford, 11908-21: "Not all materials calculated no ABS edging Allowed." The
        # engine had been MEASURING the edges and raising an estimator-input ask. That is
        # not what he asked for and it is not what an estimate is: edging is material that
        # gets bought by the metre, so it belongs in the bill of materials with a code, a
        # quantity and a price — "a distinct length-priced line".
        #
        # The QUANTITY is metres, and it comes from edge_banding: only the edges the
        # drawing marks, never the perimeter (D-104). No marked edges, no line — an edging
        # line on a part nobody bands would be the perimeter mistake with a price on it.
        #
        # The PRICE is not set here. It flows through the same chain as any other bought-in
        # — SDI Live, the supplier catalogue, a current quote, then a researched figure with
        # its evidence — so a rate the office already holds wins, and where nothing answers
        # the line reads as unpriced with its metres visible.
        #
        # AND AN ESTIMATOR CAN SUPPLY THE METRES. James Gray: "confirmed banded metres x
        # current £/metre... so, we should be able to price in this case." On 11908-21 the
        # DXFs carry no layer data and no note names an edge, so nothing measurable could
        # answer — and Tony had already said 5.0 m a tray. That is a physical extent of the
        # product, not a price, and it outranks everything inferred from the geometry. Two
        # forms: metres a FINISHED UNIT (which replaces the sum, because it already IS the
        # sum), or metres per ONE of a named part (which joins the measurement as the
        # highest-trust rung for that part).
        try:
            from edge_banding import banded_length_mm as _banded_of
            _edge_code = str(getattr(config, "FACED_BOARD_EDGING_CODE", "") or "")
            _spec = dict(getattr(config, "FACED_BOARD_EDGING_SPEC", {}) or {})
            _bm_dec = ((summary or {}).get("estimator_decisions") or {}).get(
                "banded_metres") or {}
            _bm_who = str(((summary or {}).get("estimator_decisions") or {}).get(
                "decided_by") or "the estimator")
            _bm_per_part = {str(k).upper(): v
                            for k, v in (_bm_dec.get("per_part") or {}).items()}
            _edge_mm, _edge_from = 0.0, set()
            for _p in (parts or []):
                if not isinstance(_p, dict):
                    continue
                if not (_p.get("_laminate_in_board")
                        or (_p.get("material_estimate") or {}).get(
                            "costing_material_family")):
                    continue
                _pn_e = str(_p.get("part_number") or "").strip().upper()
                if _pn_e in _bm_per_part:
                    _p["_confirmed_banded_mm"] = float(_bm_per_part[_pn_e]) * 1000.0
                    _p["_confirmed_banded_by"] = _bm_who
                _v = _banded_of(_p) or {}
                if _v.get("mm"):
                    _edge_mm += float(_v["mm"]) * float(_safe_float(_p.get("quantity")) or 1)
                    _edge_from.add(str(_v.get("basis") or ""))
            _edge_m = round(_edge_mm / 1000.0, 3)
            # A PER-UNIT CONFIRMATION IS THE WHOLE ANSWER, NOT A CONTRIBUTION TO IT. Tony's
            # 5.0 m is the banded edge across every component of one tray, so adding it to
            # what the parts measured would count the same metres twice.
            _bm_unit = _bm_dec.get("per_unit")
            if _bm_unit is not None:
                _edge_m = round(float(_bm_unit), 3)
                _edge_from = {"estimator_confirmed"}
            _already = any(str((_x or {}).get("part_number") or "").upper() == _edge_code
                           for _x in (parts or []) if isinstance(_x, dict))
            # WHERE THE METRES CAME FROM, IN THE WORDS OF WHOEVER SUPPLIED THEM. A
            # confirmed extent and a measured one are both facts and they are not the same
            # fact, and a reader deciding whether to trust the line needs to know which.
            _edge_said = ("confirmed by " + _bm_who
                          if "estimator_confirmed" in _edge_from
                          else "measured from the edges the drawing marks as banded")
            if _edge_code and _edge_m > 0 and not _already:
                _stub = _bought_in_part_stub(
                    _edge_code,
                    (f"{_spec.get('description') or 'ABS edging'} — {_edge_m:g} m a unit, "
                     f"{_edge_said}"),
                    _edge_m)
                _stub["unit_of_measure"] = "m"
                _stub["supplier"] = _spec.get("supplier") or ""
                _stub["_edging_line"] = True
                _stub["_edging_basis"] = sorted(b for b in _edge_from if b)
                _stub.setdefault("review_flags", []).append(
                    f"EDGING {_edge_m:g} m a unit on code {_edge_code} "
                    f"({_spec.get('description') or 'ABS edging'}). The METRES are "
                    f"{_edge_said} — not the perimeter. The RATE is asked of SDI Live and "
                    f"the supplier catalogue; if neither answers, the line stays visibly "
                    f"unpriced rather than carrying a rate off an old manual sheet.")
                parts.append(_stub)
                if debug:
                    print(f"[DEBUG] Added EDGING line {_edge_code} at {_edge_m:g} m/unit")
        except Exception as _edge_exc:                           # noqa: BLE001
            print(f"   [edging] line could not be built "
                  f"({type(_edge_exc).__name__}: {_edge_exc}) — no edging line on this "
                  f"job", flush=True)

        # A PLATED weldment goes out to a subcontract plater, not SDI's own powder booth, so it
        # carries a plating LINE priced on the plated steel mass — never a P.Coat row (the powder
        # gate already rules powder out on a plated part) and never the £0 it read before. One
        # line per plated weldment, minted here so it flows through the canonical graph and the
        # sheet exactly like the packaging/delivery lines; its price is set post-loop from the
        # members' own costed masses so the figure agrees with the sheet.
        try:
            _plate_policy = getattr(config, "PLATE_SUBCONTRACT_POLICY", {}) or {}
            _plate_members = (plated_steel_member_pns(parts, summary)
                              if _plate_policy.get("gbp_per_kg") is not None else set())
        except Exception:                                       # noqa: BLE001
            _plate_members = set()
        if _plate_members:
            _plated_weldments = [
                p for p in parts if isinstance(p, dict)
                and (p.get("is_assembly_parent") or p.get("is_sub_assembly"))
                and _is_plate_finish(_part_finish_text(p))]
            _wpn = (str(_plated_weldments[0].get("part_number")).strip()
                    if _plated_weldments else "PLATING")
            _plate_code = f"{_wpn}-PLATE"
            _have = {str(p.get("part_number", "")).strip().upper()
                     for p in parts if p.get("part_number")}
            if _plate_code.upper() not in _have:
                _pstub = _bought_in_part_stub(
                    _plate_code,
                    f"{_wpn} plating — INDICATIVE zinc/passivate, verify against plater quote", 1)
                _pstub["source"] = "commercial_placeholder"
                _pstub["_commercial_placeholder"] = True
                _pstub["_plating_placeholder"] = True
                _pstub["_plating_members"] = sorted(_plate_members)
                _pstub["_plating_weldment"] = _wpn
                _pstub["textual_operations"] = []
                _pstub["inferred_operations"] = []
                _pstub["price_verified"] = False
                _pstub["review_flag"] = True
                _pstub["review_flags"] = [
                    "Subcontract plating on a PLATED weldment — priced post-loop on the plated "
                    "steel mass; confirm process and mass."]
                # GIVE IT THE PARENT IT ACTUALLY HAS, IN THE FIELD THE GRAPH READS.
                #
                # This line is a finish ON the weldment, so the weldment owns it, and the
                # Canonical BOM should show the plating beside the thing being plated.
                # Appending to the parent's `assembly_children` does NOT achieve that: that
                # source is skipped for any parent the extract already states children for
                # ("the description rule only fills a hierarchy nobody expressed"), which 101
                # is — so the edge was silently dropped and the plate came out parentless.
                # The extract's own assemblies list IS honoured, so the edge goes there.
                if _plated_weldments:
                    _wpn_up = str(_plated_weldments[0].get("part_number") or "").strip()
                    _lex = (summary.setdefault("llm_full_extract", {})
                            if isinstance(summary, dict) else None)
                    if isinstance(_lex, dict):
                        _asms = _lex.setdefault("assemblies", [])
                        if isinstance(_asms, list):
                            _entry = next(
                                (a for a in _asms if isinstance(a, dict)
                                 and str(a.get("part_number") or "").strip() == _wpn_up), None)
                            if _entry is None:
                                _entry = {"part_number": _wpn_up, "children": []}
                                _asms.append(_entry)
                            _kids = _entry.setdefault("children", [])
                            if isinstance(_kids, list) and not any(
                                    isinstance(k, dict) and str(k.get("part_number") or "")
                                    .strip() == _plate_code for k in _kids):
                                _kids.append({"part_number": _plate_code, "qty": 1})
                    # kept as corroboration for any reader that prefers the parent's own list
                    _wkids = _plated_weldments[0].setdefault("assembly_children", [])
                    if isinstance(_wkids, list) and _plate_code not in _wkids:
                        _wkids.append(_plate_code)
                parts.append(_pstub)
                if debug:
                    print(f"[DEBUG] Added subcontract plating line for {_wpn} "
                          f"({len(_plate_members)} plated member(s))")

                # ---- AND GETTING IT THERE AND BACK IS A LINE, NOT A SENTENCE ----------
                #
                # "** Delivery to & from Platers from Transport Dept. For Ref. £—
                # Pallet Network - £— per unit."   — Howard Thurley, 9 Sep 2026
                #
                # The plating line carries this in its note and deliberately does not add it,
                # so that the plating figure equals what the PLATER charges and can be checked
                # against the plater's own quote. That reasoning is right and it stays. What
                # was wrong is the conclusion drawn from it: the freight then appeared on no
                # line at all, which is not "kept separate", it is "not charged". Real money
                # the job would not spend if the part were finished in house, missing from
                # the total.
                #
                # So it gets its own line, beside the plating rather than inside it. Both
                # halves of the rule are then satisfied — the plating equals the plater's
                # quote, and the freight is in the price.
                #
                # THE ROUTE INHERITS; THE MONEY DOES NOT. Any job that sends work out to a
                # platers pays to send it and pays to get it back, so the LINE exists on
                # every plated job. The FIGURE is a transport quote — the £— was
                # 7332-01's own, and holding it in config made it every plated job's
                # freight, the same fault as the £— in a smaller coat. The register
                # answers only for the job the quote belongs to; every other plated job
                # gets this line UNPRICED with the owner named, exactly like any other
                # missing quote.
                _fr_code = "PLATERFREIGHT"
                _fr_entry2 = plater_freight_for_job(job_identity_codes(summary))
                if _fr_code not in _have:
                    _fq = max(1, int(_commercial_order_quantity(summary) or 1))
                    if _fr_entry2:
                        import price_register as _preg2
                        _fr_order = _safe_float(_fr_entry2.get("amount")) or 0.0
                        _fr_unit = round(_fr_order / _fq, 2)
                        _fstub = _bought_in_part_stub(
                            _fr_code,
                            f"Delivery to and from the platers — "
                            f"£{_fr_order:.0f} the round trip over {_fq} off", 1)
                        _fstub["unit_cost_gbp"] = _fr_unit
                        _fstub["unit_material_cost_gbp"] = _fr_unit
                        _fstub["extended_total_cost_gbp"] = _fr_unit
                        _fstub["material_estimate"] = {
                            "unit_material_cost_gbp": _fr_unit,
                            "cost_per_part_gbp": _fr_unit,
                            "extended_material_cost_gbp": _fr_unit,
                            "cost_method": "plater_freight_quoted",
                        }
                        _fstub["cost_source"] = "plater_freight_quoted"
                        _fstub["costing_basis"] = "plater_freight_quoted"
                        _fstub["review_flags"] = [
                            f"plater freight: £{_fr_order:.0f} per order spread over "
                            f"{_fq} off = £{_fr_unit:.2f} a unit. NOT part of the plating "
                            f"line, which is held equal to the plater's own quote so it "
                            f"can be checked against it. Moves with the order quantity "
                            f"({_preg2.describe(_fr_entry2)}). Confirm the round trip and "
                            f"the carrier"]
                        print(f"   [plating] plater freight charged as its own line: "
                              f"£{_fr_order:.0f} / {_fq} off = £{_fr_unit:.2f} a unit",
                              flush=True)
                    else:
                        _fstub = _bought_in_part_stub(
                            _fr_code,
                            "Delivery to and from the platers — AWAITING a current "
                            "transport quote for this job", 1)
                        _fstub["unit_cost_gbp"] = None
                        _fstub["unit_material_cost_gbp"] = None
                        _fstub["extended_total_cost_gbp"] = None
                        _fstub["_price_explicitly_withheld"] = True
                        _fstub["material_estimate"] = {
                            "unit_material_cost_gbp": None,
                            "cost_per_part_gbp": None,
                            "extended_material_cost_gbp": None,
                            "cost_method": "plater_freight_awaiting_quote",
                        }
                        _fstub["cost_source"] = "plater_freight_awaiting_quote"
                        _fstub["costing_basis"] = "plater_freight_awaiting_quote"
                        _fstub["review_flags"] = [
                            "plater freight NOT PRICED: the part goes out and comes back, "
                            "so this is real money — and no current transport quote for "
                            "THIS job is on record. An earlier job's quote is that job's "
                            "and does not price this one. MISSING: the haulage figure; "
                            "ASK: SDI transport department"]
                        print("   [plating] plater freight line raised UNPRICED — no "
                              "current transport quote for this job", flush=True)
                    _fstub["source"] = "plater_freight_stated"
                    _fstub["_commercial_placeholder"] = True
                    _fstub["_plater_freight"] = True
                    _fstub["textual_operations"] = []
                    _fstub["inferred_operations"] = []
                    _fstub["price_verified"] = False
                    _fstub["review_flag"] = True
                    parts.append(_fstub)

        # SDI Intelligence — powder coating / wet spray is declared once in the
        # drawing title block (e.g. "POWDER COATED"), not per part. Stamp the
        # finish op onto fabricated metal parts so booth labour + powder
        # consumable are costed. Acrylic/board parts are not powder coated.
        _tb = ((summary.get("document_analysis") or {}).get("title_block") or {})
        _finishes = [str(x) for x in (_tb.get("surface_finishes") or []) if x]
        _finishes_blob = " ".join(_finishes).upper()
        _doc_powder = "POWDER" in _finishes_blob
        _doc_wet = any(t in _finishes_blob for t in ("WET SPRAY", "WET PAINT", "LINE PAINT", "SPRAY PAINT"))
        if _doc_powder or _doc_wet:
            _coat_op = "powder_coating" if _doc_powder else "wet_spray"
            _coat_metals = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                            "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}
            for _p in parts:
                if str(_p.get("normalized_material") or "").upper() not in _coat_metals:
                    continue
                # THE DOCUMENT'S FINISH DESCRIBES THE FABRICATED PRODUCT. This blanket
                # stamped the coat onto a purchased PEM stud because its material reads
                # MILD STEEL — a min-floor charge for coating an item that arrives
                # finished. A purchased part is only coated when ITS OWN evidence says
                # so (its row, its sheet, an LLM claim on it) — and those arrive
                # through the per-part paths, which this stamp must not stand in for.
                _p_roles = {str(r).lower() for r in (_p.get("page_roles") or [])}
                if "bought_in" in _p_roles or _p.get("bought_in") \
                        or str(_p.get("part_number") or "").upper().startswith("BI-"):
                    continue
                _existing = list(_p.get("textual_operations") or []) + list(_p.get("inferred_operations") or [])
                if _coat_op not in _existing:
                    record_operation(_p, _coat_op, "drawing_deterministic")
                if not _p.get("surface_finishes"):
                    _p["surface_finishes"] = list(_finishes)
            if debug:
                print(f"[DEBUG] {_coat_op} stamped onto metal parts from title-block finish {_finishes}")
    started = time.time()

    def _is_weldment_parent_part(p: Dict[str, Any], all_parts: List[Dict[str, Any]]) -> bool:
        """
        Skip SA weldment parent lines when fabricated child parts exist on the same
        drawing prefix (e.g. 10777-01-SA01 vs 10777-01-01/02/03) to avoid double-count.
        """
        pn = str(p.get("part_number") or "").upper().strip()
        if not re.search(r"-SA\d*$", pn):
            return False
        prefix = re.sub(r"-SA\d*$", "", pn)
        if not prefix:
            return False
        children = [
            x for x in all_parts
            if str(x.get("part_number") or "").upper().startswith(prefix + "-")
            and not re.search(r"-SA\d*$", str(x.get("part_number") or "").upper())
            and not str(x.get("part_number") or "").upper().endswith("-GA")
        ]
        if not children:
            return False
        desc = str(p.get("description") or "").upper()
        if any(k in desc for k in ("WELDMENT", "WELD ASSY", "WELDED ASSEMBLY", "FRAME WELDMENT")):
            return True
        # Generic SA row (12137-03-SA etc.) — skip when leaf parts are costed separately
        if "dxf" not in str(p.get("geometry_source") or "").lower():
            return True
        return False

    def _is_estimable_part(p: Dict[str, Any]) -> bool:
        """Return False for junk parts that have no meaningful content to estimate."""
        # Suppress NAMELESS phantom parts: part_number AND description both empty/None. These arise
        # from SECTION/DETAIL callouts (e.g. page-21 SECTION G-G is a view of BACK WALL 12532-03-06M,
        # already costed) that the extractor turned into a separate record with no identity. A real
        # fabricated part always has at least a part number, so keying on namelessness suppresses
        # only the phantom (proven: exactly one nameless record; 'has section callout' is NOT safe
        # to key on because real parts also carry section views). Must run BEFORE the has_dims/has_ops
        # rescue below, since the phantom carries incidental geometry that would otherwise keep it.
        _pn_raw = str(p.get("part_number") or "").strip()
        _desc_raw = str(p.get("description") or "").strip()
        if _pn_raw in ("", "None") and _desc_raw in ("", "None"):
            return False
        # Suppress GA/SA overview parts with no DXF geometry
        _pn_up = str(p.get("part_number") or "").upper().rstrip("_")
        _geo = str(p.get("geometry_source") or "")
        if ((_pn_up.endswith("-GA") or _pn_up.endswith("-GA1") or
             _pn_up.endswith("-SA") or _pn_up.endswith("-SA01"))
                and "dxf" not in _geo.lower()
                and not p.get("description")):
            return False
        has_part_number = bool(
            p.get("part_number")
            and not str(p.get("part_number", "")).startswith("part_")
            and str(p.get("part_number", "")).strip() not in ("", "None", "?")
        )
        has_material = bool(
            p.get("normalized_material")
            and str(p.get("normalized_material", "")).strip() not in ("", "None", "?", "UNKNOWN")
        )
        has_dims = bool(
            _safe_float(p.get("blank_length_mm"))
            or _safe_float(p.get("overall_length_mm"))
            or _safe_float(p.get("blank_width_mm"))
        )
        has_ops = bool(
            p.get("fab_ops")
            or p.get("operations")
            or p.get("textual_operations")
            or (p.get("manufacturing_features") or {}).get("operations")
            or p.get("_bought_in_from_text_scan")
        )
        return has_part_number or has_material or has_dims or has_ops

    # Reconcile cross-layer duplicate bought-in lines (same item, different identifier/source)
    # before estimation, so a doubled loom / rivet / fixing can't reach the workbook. Keeps
    # the most-grounded source, drops the duplicate, flags the merge for audit. The pooled page
    # text lets reconciliation use drawing co-location ("FIXING5 ... DOME RIVET") as a merge
    # signal in addition to description-token overlap.
    _recon_text = ""
    if summary is not None:
        try:
            _pgs = summary.get("pages", []) or []
            _recon_text = " ".join(
                str(_pg.get("pdfplumber_text", "") or "") + " "
                + str(_pg.get("normalized_text", "") or "") + " "
                + _page_text_for_bought_in_scan(_pg)
                for _pg in _pgs
            ).upper()
        except Exception:
            _recon_text = ""
    parts = _reconcile_bought_in(parts, all_text=_recon_text, debug=debug)

    estimable_parts = [
        p for p in parts
        if _is_estimable_part(p) and not _is_weldment_parent_part(p, parts)
    ]
    skipped = len(parts) - len(estimable_parts)
    if skipped:
        print(f"   -> Skipped {skipped} junk part(s) with no material, dimensions, or operations")

    # Order quantity for setup/batch amortisation: the per-job qty the scan
    # captured (summary['assumed_job_quantity']; file_scan stamps
    # DEFAULT_JOB_QUANTITY when the enquiry doesn't state one). Passed into every
    # part so machine setup is spread over the order — as the manual estimate does.
    _order_qty = None
    if summary is not None:
        _order_qty = summary.get("assumed_job_quantity") or summary.get("quantity")
    _order_qty = max(1, int(_order_qty or getattr(config, "DEFAULT_JOB_QUANTITY", 180)))
    if debug:
        print(f"[DEBUG] estimate_document order_qty for setup amortisation = {_order_qty}")

    # THE CUSTOMER'S FINISH STANDARD RIDES DOWN TO EVERY PART. "M&S dress all seen welds;
    # TTI none" is a job-level fact and estimate_part never sees the summary, so it is
    # stamped here — resolved from the SAME customer name the workbook header prints
    # (job_customer), which is the lesson the £— register learned the hard way.
    _finish_std = customer_finish_standard(job_customer(summary)) if summary else None

    # WHAT EACH BOUGHT-IN LINE IS, for the research brief — its other names in the pack and
    # the assembly it sits in. See research_context: the Yiree screw was researched as a bare
    # supplier code and came back at £126.04 each.
    try:
        from research_context import stamp_research_context
        stamp_research_context(estimable_parts, summary)
    except Exception as _rc_exc:                                     # noqa: BLE001
        print(f"   [pricing] research context not stamped ({_rc_exc})", flush=True)

    part_estimates: List[Dict[str, Any]] = []
    _failed_parts: List[Dict[str, Any]] = []
    for idx, part in enumerate(estimable_parts, start=1):
        part_number = part.get("part_number") or part.get("item_number") or f"part_{idx}"
        if debug:
            print(
                f"[DEBUG] estimate_document start part {idx}/{len(estimable_parts)}: "
                f"{part_number} (+{round(time.time()-started,2)}s)"
            )
        if _finish_std and not part.get("_customer_finish_standard"):
            part["_customer_finish_standard"] = dict(_finish_std)
        # ONE PART MUST NOT DESTROY THE JOB.
        #
        # 401912-02, twice in twenty minutes: a `KeyError` costing the magnetic tape ended
        # the process, and the DXF augment, the SolidWorks extract, the SQL price lookups and
        # every other part on the job went in the bin with it. "The engine exited with code
        # 1. Nothing was filed." Forty-nine seconds of work, and an estimator with nothing to
        # look at — not even the parts that costed perfectly well.
        #
        # The trade here is not "hide the error". It is WHICH failure an estimator is handed:
        # a job with one line marked NOT COSTED and a traceback attached to it, or no job at
        # all. The first can be read, priced by hand and sent; the second cannot be anything.
        #
        # So the part is dropped from the costed record rather than half-built — nothing
        # downstream should ever meet a partially costed part, which is how a £0 reaches a
        # total — and the failure is made impossible to miss: on the log, on the summary, and
        # on the job's own outstanding list. The rule this engine already follows everywhere
        # else: SAID, NOT STOPPED.
        try:
            part_estimate = estimate_part(part, job_quantity=_order_qty)
        except Exception as _exc_part:                               # noqa: BLE001
            import traceback as _tb_part
            _why_part = f"{type(_exc_part).__name__}: {_exc_part}"
            _failed_parts.append({
                "part_number": part_number,
                "description": part.get("description") or "",
                "error": _why_part,
                "traceback": _tb_part.format_exc(),
            })
            print(f"   [cost] {part_number} COULD NOT BE COSTED — {_why_part}. The rest of "
                  f"the job is costed and this line is on the outstanding list.", flush=True)
            continue
        part_estimates.append(part_estimate)
        if debug:
            print(
                f"[DEBUG] estimate_document done part {idx}/{len(estimable_parts)}: "
                f"{part_number} (+{round(time.time()-started,2)}s)"
            )
    # AND THE JOB SAYS WHAT IS MISSING FROM IT. A part dropped from the costed record is a
    # hole in the total, so it goes on the summary's own review flags — the list an estimator
    # reads before sending anything — rather than only into a log line that scrolls away.
    if _failed_parts and summary is not None:
        try:
            _rf_job = summary.setdefault("review_flags", [])
            if isinstance(_rf_job, list):
                for _fp in _failed_parts:
                    _rf_job.append(
                        f"NOT COSTED — {_fp['part_number']}"
                        + (f" ({_fp['description']})" if _fp.get("description") else "")
                        + f": {_fp['error']}. This line is MISSING FROM THE TOTAL and must "
                          f"be priced by hand before the estimate is sent.")
            summary["parts_that_failed_to_cost"] = list(_failed_parts)
        except Exception:                                        # noqa: BLE001
            pass

    # ALWAYS A NUMBER. After every part is costed, any REAL line still reading as free gets a
    # per-each market/LLM indicative so £0 never sits on a part the shop actually buys. Runs
    # AFTER the loop (so the seal's early return has already fired) AND refuses the seal markers
    # explicitly (so a queried FOOTPLATE can never be re-priced here). Non-firm, flagged.
    try:
        _rescued = apply_last_resort_prices(part_estimates, _last_resort_lookup)
        if _rescued:
            print(f"   [always-a-number] {_rescued} line(s) that read as free were given a "
                  f"non-firm market/LLM indicative so no real part shows a blank price")
    except Exception as _e_lr:                                   # noqa: BLE001
        print(f"   [always-a-number] last-resort pricing skipped: {_e_lr}")
    # Price the subcontract plating line(s) now that every member has a costed mass, so the
    # plated-mass figure agrees with the sheet. Runs before the totals below so the plating cost
    # is in them.
    try:
        _plated_n = apply_subcontract_plating(part_estimates, summary, _order_qty, parts)
        if _plated_n:
            print(f"   [plating] priced {_plated_n} subcontract plating line(s) on plated mass")
    except Exception as _e_pl:                                   # noqa: BLE001
        print(f"   [plating] subcontract plating pass skipped: {_e_pl}")
    material_total_raw = sum((item.get("material_estimate", {}).get("extended_material_cost_gbp") or 0.0) for item in part_estimates)
    labour_total_raw = sum((item.get("labour_estimate", {}).get("total_labour_cost_gbp") or 0.0) for item in part_estimates)
    material_total = _round_money(material_total_raw)
    labour_total = _round_money(labour_total_raw)
    operation_totals: Dict[str, float] = {}
    for item in part_estimates:
        for op, cost in item.get("labour_estimate", {}).get("costs_gbp", {}).items():
            operation_totals[op] = round(operation_totals.get(op, 0.0) + (cost or 0.0), 2)
    mode = _rounding_mode()
    if mode == "per_line":
        document_total_raw = sum(float(item.get("extended_total_cost_gbp") or 0.0) for item in part_estimates)
    else:
        document_total_raw = sum(float(item.get("extended_total_cost_raw_gbp") or item.get("extended_total_cost_gbp") or 0.0) for item in part_estimates)
    if mode == "per_section":
        document_total_raw = material_total + labour_total
    document_total = _round_money(document_total_raw)

    data_sufficiency = _assess_estimate_data_sufficiency(
        estimable_parts, part_estimates, document_total
    )
    reportable_total = data_sufficiency.get("document_total_reportable_gbp")
    # THE TOTAL IS ALWAYS REPORTED. It was nulled on a job the gate judged thin, which left
    # every deliverable with a blank where the price goes and an estimator with nothing —
    # while the workbook went on and computed a unit cost regardless, because that is a
    # different figure. The doubt is carried by data_sufficiency.provisional and stated on
    # the estimate; it is no longer expressed by withholding the number.
    document_total_out = document_total

    powder_material_total_raw = sum(_part_powder_material_extended_gbp(p) for p in part_estimates)
    powder_labour_total_raw = sum(_part_powder_labour_gbp(p) for p in part_estimates)
    pc_policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    pc_labour = LABOUR_RULES.get("powder_coating", {}) or {}
    powder_scrap_frac = (
        float(getattr(config, "SCRAP_PERCENTAGE", 0.0) or 0.0) if pc_policy.get("apply_global_scrap_to_powder_kg", True) else 0.0
    )
    powder_coating_summary = {
        "powder_material_gbp": _round_money(powder_material_total_raw),
        "powder_labour_gbp": _round_money(powder_labour_total_raw),
        "powder_total_gbp": _round_money(powder_material_total_raw + powder_labour_total_raw),
        "costing_inputs": {
            "coverage_m2_per_kg": float(pc_policy.get("coverage_m2_per_kg", 6.0)),
            "throughput_m2_per_hour": float(pc_labour.get("throughput_m2_per_hour", 15.0)),
            "setup_min_per_part": float(pc_labour.get("setup_min_per_part", pc_labour.get("min_per_part", 0.75))),
            "min_run_min": float(pc_labour.get("min_run_min", 0.25)),
            "hourly_rate_powder_coating_gbp": float(HOURLY_RATES_GBP.get("powder_coating", 0.0) or 0.0),
            "powder_material_gbp_per_kg_standard": float(pc_policy.get("powder_material_gbp_per_kg", 0.0)),
            "powder_material_gbp_per_kg_special_finish": float(pc_policy.get("powder_material_gbp_per_kg_special", 0.0)),
            "global_scrap_fraction_on_powder_kg": powder_scrap_frac,
            "bend_coating_strip_mm": float(pc_policy.get("bend_coating_strip_mm", 40.0)),
        },
        "one_line": (
            f"Powder coating: £{_round_money(powder_material_total_raw):.2f} material + "
            f"£{_round_money(powder_labour_total_raw):.2f} labour"
        ),
        "by_part": [
            {
                "part_number": p.get("part_number"),
                "description": p.get("description"),
                "quantity": p.get("quantity"),
                "powder_material_gbp": _round_money(_part_powder_material_extended_gbp(p)),
                "powder_labour_gbp": _round_money(_part_powder_labour_gbp(p)),
                "powder_total_gbp": _round_money(
                    _part_powder_material_extended_gbp(p) + _part_powder_labour_gbp(p)
                ),
            }
            for p in part_estimates
            if _part_powder_material_extended_gbp(p) > 0 or _part_powder_labour_gbp(p) > 0
        ],
    }

    workbook_equivalent_pricing = _build_workbook_equivalent_pricing(
        part_estimates, material_total=material_total, labour_total=labour_total,
        customer=((summary or {}).get("customer") or (summary or {}).get("client")))
    estimate_source_extract = build_estimate_source_extract(part_estimates)
    historical_comparison_projection = {
        "schema": "estimate_projection_for_historical.v1",
        "totals": {
            "material_subtotal_gbp": material_total,
            "labour_subtotal_gbp": labour_total,
            "document_total_estimated_cost_gbp": reportable_total if reportable_total is not None else document_total_out,
            "workbook_equivalent_total_unit_cost_gbp": workbook_equivalent_pricing.get("l105_total_unit_cost_gbp"),
            "workbook_equivalent_sell_price_gbp": workbook_equivalent_pricing.get("l111_sell_price_gbp"),
        },
        "parts": [
            {
                "part_number": p.get("part_number"),
                "description": p.get("description"),
                "quantity": p.get("quantity"),
                "unit_total_cost_gbp": p.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": p.get("extended_total_cost_gbp"),
                "material_cost_gbp": p.get("cost_breakdown", {}).get("material", {}).get("extended_material_cost_gbp"),
                "labour_cost_gbp": p.get("cost_breakdown", {}).get("labour", {}).get("total_labour_cost_gbp"),
                "costing_basis": p.get("cost_breakdown", {}).get("costing_basis"),
                "operations_costs_gbp": p.get("cost_breakdown", {}).get("labour", {}).get("costs_gbp", {}),
            }
            for p in part_estimates
        ],
    }

    # Compile the route in shadow mode. The workbook remains on its legacy path until the
    # 2085 and 12120 projections agree and the cutover is explicitly enabled.
    try:
        from route_compiler import (compile_job_route, declared_product_of,
                                    project_priced_route)
        # The writeup's finish text rides along: it is the population that actually
        # carries "SEE ASSEMBLY DRAWING" when the estimate records do not (11350-02's
        # bar), and the coat pass must read the field the report already prints.
        _finish_by_pn = {}
        for _wp in (((summary or {}).get("manufacturing_writeup") or {}).get("parts")
                    or []) if isinstance(summary, dict) else []:
            if not isinstance(_wp, dict):
                continue
            _wpn = str(_wp.get("part_number") or "").strip().upper()
            if _wpn:
                _finish_by_pn[_wpn] = " ".join(
                    [str(_wp.get("normalized_finish") or "")]
                    + [str(x) for x in (_wp.get("surface_finishes") or [])])
        _route_graph = compile_job_route(
            parts,
            (summary or {}).get("llm_full_extract")
            if isinstance(summary, dict) else {},
            finish_text_by_pn=_finish_by_pn,
            declared_product=declared_product_of(
                summary if isinstance(summary, dict) else {}),
        )
        canonical_route_shadow = project_priced_route(
            _route_graph, part_estimates)
    except Exception as route_error:
        # A shadow diagnostic must never turn an executable estimate into a fallback sheet.
        # The failure is stamped for review and will become blocking before cutover.
        canonical_route_shadow = {
            "schema": "priced_route_shadow.v1",
            "mode": "shadow",
            "compiler_error": f"{type(route_error).__name__}: {route_error}",
            "nodes": [],
            "decisions": [],
            "priced_route_rows": [],
            "issues": [{
                "code": "canonical_route_compiler_failed",
                "message": f"{type(route_error).__name__}: {route_error}",
            }],
        }

    out_doc: Dict[str, Any] = {
        # WHICH BUILD PRODUCED THIS DOCUMENT. Stamped at write time, because a diagnostic
        # reading the estimate later reports the build of the checkout it is reading FROM,
        # which may be days of pulls away from the one that wrote it.
        "engine_build": engine_build.describe(),
        "part_estimates": part_estimates,
        "canonical_route_shadow": canonical_route_shadow,
        "powder_coating_summary": powder_coating_summary,
        "estimate_policy_manifest": _build_estimate_policy_manifest(),
        "estimate_review_signals": _build_estimate_review_signals(part_estimates),
        "data_sufficiency": data_sufficiency,
        "estimate_status": data_sufficiency.get("status", "ok"),
        "document_total_estimated_cost_gbp": reportable_total if reportable_total is not None else document_total_out,
        "document_total_provisional_gbp": data_sufficiency.get("document_total_provisional_gbp"),
        "document_total_raw_gbp": document_total_raw,
        "workbook_equivalent_pricing": workbook_equivalent_pricing,
        "estimate_source_extract": estimate_source_extract,
        "historical_comparison_projection": historical_comparison_projection,
        "cost_breakdown": {
            "material": {
                "total": material_total,
                "per_part": [
                    {
                        "part_number": item.get("part_number"),
                        "extended_material_cost_gbp": item.get("material_estimate", {}).get("extended_material_cost_gbp"),
                        "supplier_source": item.get("material_estimate", {}).get("price_source", {}).get("supplier_source"),
                        "price_date": item.get("material_estimate", {}).get("price_source", {}).get("price_date"),
                    }
                    for item in part_estimates
                ],
            },
            "labour": {
                "total": labour_total,
                "by_operation": operation_totals,
            },
            "overhead": {},
            "margin_options": ["low", "standard", "premium"],
            "pricing_metadata": {
                "latest_price_date": max(
                    [item.get("material_estimate", {}).get("price_source", {}).get("price_date") for item in part_estimates if item.get("material_estimate", {}).get("price_source", {}).get("price_date")],
                    default=None,
                ),
                "supplier_sources": sorted(
                    {
                        item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                        for item in part_estimates
                        if item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                    }
                ),
                "pricing_basis": "external_or_config_fallback",
            },
        },
    }
    wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    # THE QUANTITY THIS JOB WAS COSTED AT, NOT THE TEMPLATE'S DEFAULT.
    #
    # The client quote reads its "Order quantity" from this field. It carried the WORKBOOK
    # DEFAULT — 180 — so a job costed at 10 was quoted as "180 off" at the ten-off price:
    # a document that is wrong in the one number a customer checks first, beside a price
    # that is right. The Estimate sheet said 10 on the same run, from the same JSON.
    #
    # A default is what to assume when the job says nothing. This job says 10, and it says
    # it in the field every part's setup amortisation divided by.
    _job_qty = (summary or {}).get("quantity") or (summary or {}).get("assumed_job_quantity")
    try:
        _job_qty = int(_job_qty) if _job_qty else None
    except (TypeError, ValueError):
        _job_qty = None
    out_doc["estimate_workbook_inputs"] = {
        "estimate_policy_version": getattr(config, "ESTIMATE_POLICY_VERSION", ""),
        "assumed_job_quantity": _job_qty or wb_defaults.get("default_job_quantity"),
        "assumed_job_quantity_source": "job" if _job_qty else "workbook_default",
        "scrap_pct": wb_defaults.get("scrap_pct"),
        "wire_cost_per_tonne_gbp": wb_defaults.get("wire_cost_per_tonne_gbp"),
        "sheet_steel_cost_per_tonne_gbp": wb_defaults.get("sheet_steel_cost_per_tonne_gbp"),
        "output_manufacturing_cost_only": bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)),
        "material_price_break_headers": getattr(config, "MATERIAL_PRICE_BREAK_HEADERS", {}),
        "workbook_source_map": getattr(config, "WORKBOOK_SOURCE_MAP", {}),
        "reverse_engineer": "Run: python src/extract_workbook_constants.py --workbook <path-to.xlsx>",
    }
    _merge_sheet_into_estimate_workbook_inputs(out_doc, summary)
    mopts = out_doc["cost_breakdown"].get("margin_options")
    if bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)) and isinstance(mopts, list):
        out_doc["cost_breakdown"]["margin_options"] = []
    return out_doc


def build_estimate_input_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    estimate_lookup = {item["part_number"]: item for item in summary.get("estimate_summary", {}).get("part_estimates", [])}

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        estimate = estimate_lookup.get(part.get("part_number"), {})
        material_estimate = estimate.get("material_estimate", {})
        process_estimate = estimate.get("process_estimate", {})
        labour_estimate = estimate.get("labour_estimate", {})
        rows.append(
            {
                "source_file": summary["source_file"],
                "part_number": part.get("part_number"),
                "description": part.get("description"),
                "quantity": part.get("quantity"),
                "page_roles": _join(part.get("page_roles", [])),
                "material": _join(part.get("materials", [])),
                "thickness_mm": _join(part.get("thicknesses_mm", [])),
                "finish": _join(part.get("surface_finishes", [])),
                "colour": _join(part.get("colours", [])),
                "revision": _join(part.get("revisions", [])),
                "dates": _join(part.get("dates", [])),
                "overall_length_mm": part.get("overall_length_mm"),
                "overall_width_mm": part.get("overall_width_mm"),
                "overall_sizes_mm": _join(part.get("overall_sizes_mm", [])),
                "dimensions_mm": _join(part.get("all_dimensions_mm", [])),
                "angles_deg": _join(part.get("angles_deg", [])),
                "hole_sizes_mm": _join(part.get("hole_sizes_mm", [])),
                "slot_sizes_mm": _join(part.get("slot_sizes_mm", [])),
                "manufacturing_features": _join(
                    [
                        f"laser={part.get('manufacturing_features', {}).get('laser_required')}",
                        f"fold={part.get('manufacturing_features', {}).get('fold_required')}",
                        f"holes={part.get('manufacturing_features', {}).get('hole_count')}",
                        f"slots={part.get('manufacturing_features', {}).get('slot_count')}",
                        f"bends={part.get('manufacturing_features', {}).get('bend_count')}",
                        f"finish={part.get('manufacturing_features', {}).get('finish_required')}",
                    ]
                ),
                "operations": _join(part.get("textual_operations", [])),
                "process_notes": _join(part.get("process_notes", [])),
                "estimated_cut_length_mm": process_estimate.get("cut_length_mm"),
                "estimated_hole_count": process_estimate.get("hole_count"),
                "estimated_slot_like_features": part.get("geometry_rollup", {}).get("estimated_slot_like_features"),
                "estimated_bend_line_count": process_estimate.get("bend_count"),
                "blank_length_mm": material_estimate.get("blank_length_mm"),
                "blank_width_mm": material_estimate.get("blank_width_mm"),
                "material_cost_gbp": material_estimate.get("extended_material_cost_gbp"),
                "total_time_min": process_estimate.get("total_time_min"),
                "unit_labour_cost_gbp": labour_estimate.get("total_labour_cost_gbp"),
                "unit_total_cost_gbp": estimate.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": estimate.get("extended_total_cost_gbp"),
            }
        )
    return rows


def generate_client_quote_pack(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean executive summary + full priced breakdown for PDF or customer email.
    Expects scan-style summary with estimate_summary (from estimate_document).
    """
    estimate = summary.get("estimate_summary") or {}
    powder = estimate.get("powder_coating_summary") or {}
    part_estimates = estimate.get("part_estimates") or []

    total_manufacturing = float(estimate.get("document_total_estimated_cost_gbp") or 0.0)
    cb = estimate.get("cost_breakdown") or {}
    total_material = float((cb.get("material") or {}).get("total") or 0.0)
    total_labour = float((cb.get("labour") or {}).get("total") or 0.0)

    wb_def = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    assumed_qty = int(wb_def.get("default_job_quantity", getattr(config, "DEFAULT_JOB_QUANTITY", 600)))
    scrap_pct = int(round(float(getattr(config, "SCRAP_PERCENTAGE", 0.04)) * 100))
    pcov = float((getattr(config, "POWDER_COSTING_POLICY", {}) or {}).get("coverage_m2_per_kg", 6.0))
    mfg_only = bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False))

    stem = Path(str(summary.get("source_file") or "drawing")).stem
    key_assumptions = [
        (
            "Manufacturing cost only (sales margin applied separately)"
            if mfg_only
            else "Costs shown before optional sales margin uplift (see internal workbook policy)."
        ),
        f"{scrap_pct}% material scrap allowance",
        f"Powder coverage {pcov:g} m² per kg",
        "Geometry-derived labour times (verify against drawing before production)",
    ]

    pack: Dict[str, Any] = {
        "schema": "client_quote_pack.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "drawing_reference": summary.get("source_file", "unknown"),
        "executive_summary": {
            "one_page_header": f"Manufacturing Cost Estimate – {stem}",
            "total_manufacturing_cost_gbp": round(total_manufacturing, 2),
            "total_material_gbp": round(total_material, 2),
            "total_labour_gbp": round(total_labour, 2),
            "powder_coating_summary": powder.get("one_line") or "Powder coating: not applicable",
            "assumed_order_quantity": assumed_qty,
            "key_assumptions": key_assumptions,
        },
        "full_priced_breakdown": {
            "parts": [
                {
                    "part_number": p.get("part_number"),
                    "description": p.get("description"),
                    "quantity": p.get("quantity"),
                    "unit_total_cost_gbp": round(float(p.get("unit_total_cost_gbp") or 0.0), 2),
                    "extended_total_cost_gbp": round(float(p.get("extended_total_cost_gbp") or 0.0), 2),
                    "material_cost_gbp": round(float((p.get("material_estimate") or {}).get("extended_material_cost_gbp") or 0.0), 2),
                    "labour_cost_gbp": round(float((p.get("labour_estimate") or {}).get("total_labour_cost_gbp") or 0.0), 2),
                    "powder_material_gbp": round(_part_powder_material_extended_gbp(p), 2),
                    "powder_labour_gbp": round(_part_powder_labour_gbp(p), 2),
                }
                for p in part_estimates
            ],
            "totals": {
                "material_subtotal_gbp": round(total_material, 2),
                "labour_subtotal_gbp": round(total_labour, 2),
                "powder_material_gbp": round(float(powder.get("powder_material_gbp") or 0.0), 2),
                "powder_labour_gbp": round(float(powder.get("powder_labour_gbp") or 0.0), 2),
                "grand_total_manufacturing_cost_gbp": round(total_manufacturing, 2),
            },
        },
        "notes_for_customer": [
            "All prices shown are manufacturing cost only.",
            "Final selling price will include SDI margin and any agreed commercial terms.",
            "Quantities and lead times subject to confirmation.",
            "Geometry and process assumptions are derived from the drawing; final verification recommended before production.",
        ],
    }

    return pack


def append_rows_to_csv(csv_path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    row_list = list(rows)
    if not row_list:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerows(row_list)
