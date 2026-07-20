"""
calibration.py — SDI Intelligence

Turns the engine from a label-fixer into a measurable estimator. Three jobs,
all built so the core functions take plain rows/dicts (testable offline) with
thin SDILive fetch helpers on top.

  1. CALIBRATION SCORECARD — diff engine output against AIEstimating.Historical
     Estimates (the ground truth) per part: delta, direction, systematic bias,
     coverage, worst offenders. This is "learning made visible": it shows how
     far out we are and which parts/materials drive the gap.

  2. CONFIDENCE + PROVISOS — one place that aggregates every signal we already
     track (geometry reliability, material source, bought-in confidence, the
     learning-engine flags, and the calibration delta) into a single per-line
     {confidence_pct, provisos[]}. This absorbs post_scan's _learning_flag so
     flags and confidence are the same system, and each proviso names the issue
     AND points at the fix so it's a worklist item, not a shrug.

  3. SOURCE-OVERLAP TEST — compare the spreadsheet price book against Historical
     Estimates so we can decide a single source of truth and not maintain two.

No confident wrong numbers: a part with no historical comparator is reported as
"unvalidated", never as a spurious delta.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════

def _norm_pn(pn: Any) -> str:
    return str(pn or "").upper().strip()


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _reliability(part: Dict[str, Any]) -> float:
    """Best-effort geometry reliability from the several places it can live."""
    r = part.get("dxf_geometry_reliability")
    if r is not None:
        return _f(r)
    geo = part.get("geometry") or {}
    conf = geo.get("confidence") if isinstance(geo, dict) else {}
    if isinstance(conf, dict) and conf.get("geometry_reliability") is not None:
        return _f(conf["geometry_reliability"])
    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 1. CALIBRATION SCORECARD (engine vs AIEstimating.HistoricalEstimates)
# ══════════════════════════════════════════════════════════════════════════════

def index_historical(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate HistoricalEstimates rows by part number: avg/min/max unit cost,
    sample count, materials seen. Rows use the table's column names (PartNumber,
    UnitCost, Material) — case-insensitively tolerated."""
    by_pn: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows or []:
        pn = _norm_pn(r.get("PartNumber") or r.get("part_number"))
        if not pn:
            continue
        by_pn.setdefault(pn, []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for pn, rs in by_pn.items():
        costs = [_f(r.get("UnitCost", r.get("unit_cost"))) for r in rs]
        costs = [c for c in costs if c > 0]
        if not costs:
            continue
        mats = {str(r.get("Material") or r.get("material") or "").upper()
                for r in rs if (r.get("Material") or r.get("material"))}
        out[pn] = {
            "n": len(costs),
            "avg": round(sum(costs) / len(costs), 4),
            "min": round(min(costs), 4),
            "max": round(max(costs), 4),
            "materials": sorted(m for m in mats if m),
        }
    return out


def calibrate_part(
    part: Dict[str, Any], hist_index: Dict[str, Dict[str, Any]], tol: float = 0.15
) -> Dict[str, Any]:
    """Compare one engine part to its historical comparator."""
    pn = _norm_pn(part.get("part_number"))
    eng = _f(part.get("unit_estimate"))
    rec = hist_index.get(pn)
    line: Dict[str, Any] = {
        "part_number": part.get("part_number"),
        "engine_unit_gbp": round(eng, 4),
        "hist_unit_gbp": None,
        "n_samples": 0,
        "delta_gbp": None,
        "delta_pct": None,
        "direction": "no_ground_truth",
        "material_match": None,
        "provisos": [],
    }
    if not rec:
        line["provisos"].append("no historical comparator — unvalidated")
        return line

    h = rec["avg"]
    line["hist_unit_gbp"] = h
    line["n_samples"] = rec["n"]
    line["delta_gbp"] = round(eng - h, 4)
    line["delta_pct"] = round((eng - h) / h * 100, 1) if h else None

    if h <= 0:
        line["direction"] = "no_ground_truth"
        line["provisos"].append("historical cost is zero/blank — unvalidated")
        return line

    rel = abs(eng - h) / h
    if rel <= tol:
        line["direction"] = "close"
    elif eng > h:
        line["direction"] = "over"
        line["provisos"].append(
            f"engine \u00a3{eng:.2f} vs historical \u00a3{h:.2f} "
            f"(n={rec['n']}) \u2014 +{line['delta_pct']:.0f}% high, review"
        )
    else:
        line["direction"] = "under"
        line["provisos"].append(
            f"engine \u00a3{eng:.2f} vs historical \u00a3{h:.2f} "
            f"(n={rec['n']}) \u2014 {line['delta_pct']:.0f}% low, review"
        )

    eng_mat = str(part.get("normalized_material") or "").upper()
    if eng_mat and rec["materials"]:
        line["material_match"] = eng_mat in rec["materials"]
        if not line["material_match"]:
            line["provisos"].append(
                f"material engine={eng_mat} vs historical={'/'.join(rec['materials'])}"
            )
    return line


def build_scorecard(
    engine_parts: List[Dict[str, Any]],
    historical_rows: List[Dict[str, Any]],
    tol: float = 0.15,
) -> Dict[str, Any]:
    """Full engine-vs-actual scorecard for a job."""
    hist_index = index_historical(historical_rows)
    lines = [calibrate_part(p, hist_index, tol) for p in engine_parts]

    matched = [l for l in lines if l["direction"] in ("close", "over", "under")]
    eng_total = round(sum(_f(l["engine_unit_gbp"]) for l in lines), 2)
    eng_matched = round(sum(_f(l["engine_unit_gbp"]) for l in matched), 2)
    hist_matched = round(sum(_f(l["hist_unit_gbp"]) for l in matched), 2)

    signed = [l["delta_pct"] for l in matched if l["delta_pct"] is not None]
    bias = round(sum(signed) / len(signed), 1) if signed else None

    worst = sorted(
        matched, key=lambda l: abs(_f(l["delta_gbp"])), reverse=True
    )[:5]

    return {
        "lines": lines,
        "summary": {
            "parts_total": len(lines),
            "parts_matched": len(matched),
            "coverage_pct": round(100 * eng_matched / eng_total, 1) if eng_total else 0.0,
            "engine_total_matched_gbp": eng_matched,
            "historical_total_matched_gbp": hist_matched,
            "overall_delta_pct": (
                round((eng_matched - hist_matched) / hist_matched * 100, 1)
                if hist_matched else None
            ),
            "systematic_bias_pct": bias,  # +ve = engine runs high on average
            "worst_offenders": [
                {"part_number": l["part_number"], "delta_gbp": l["delta_gbp"],
                 "delta_pct": l["delta_pct"], "direction": l["direction"]}
                for l in worst
            ],
            "unvalidated_parts": [
                l["part_number"] for l in lines if l["direction"] == "no_ground_truth"
            ],
        },
    }


def fetch_historical_rows(conn, part_numbers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Live helper: pull HistoricalEstimates rows (optionally for given PNs)."""
    cur = conn.cursor()
    if part_numbers:
        marks = ",".join("?" * len(part_numbers))
        cur.execute(
            f"SELECT PartNumber, Material, ThicknessMm, Quantity, UnitCost, TotalCost "
            f"FROM AIEstimating.HistoricalEstimates "
            f"WHERE UnitCost > 0 AND PartNumber IN ({marks})",
            *[_norm_pn(p) for p in part_numbers],
        )
    else:
        cur.execute(
            "SELECT PartNumber, Material, ThicknessMm, Quantity, UnitCost, TotalCost "
            "FROM AIEstimating.HistoricalEstimates WHERE UnitCost > 0"
        )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONFIDENCE + PROVISOS  (absorbs the learning-engine flags)
# ══════════════════════════════════════════════════════════════════════════════

def line_confidence_and_provisos(
    part: Dict[str, Any], calib_line: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """One confidence figure + a provisos worklist per line, from every signal
    we already hold. Absorbs post_scan's _learning_flag so flags and confidence
    are a single system."""
    provisos: List[str] = []
    geo_src = str(part.get("geometry_source") or "").lower()
    rel = _reliability(part)
    inferred = bool(part.get("geometry_inferred"))

    # base from geometry provenance
    needs_dxf = False
    pdf_reason = ""
    if inferred:
        conf, basis = 0.40, "geometry inferred (no DXF) — provisional"
        provisos.append("blank size inferred, no flat DXF — provisional, verify")
        needs_dxf = True
        pdf_reason = (
            "no flat pattern supplied, so the blank size and hole/bend counts are inferred "
            "from title-block dimensions the drawing does not fully constrain"
        )
    elif "dxf" in geo_src and rel >= 0.9:
        conf, basis = 0.90, "DXF-exact geometry"
    elif "dxf" in geo_src and rel >= 0.7:
        conf, basis = 0.75, "DXF geometry, moderate reliability"
    elif "pdf" in geo_src and rel < 0.5:
        conf, basis = 0.30, "PDF-only geometry, low reliability"
        provisos.append("geometry from PDF vectors only (no DXF) — low reliability")
        needs_dxf = True
        pdf_reason = (
            "cut length is summed from every vector on the PDF sheet — title block, dimension "
            "lines and detail views at different scales — so it overstates the true profile and "
            "cannot isolate a clean flat blank; hole and bend counts are unreliable"
        )
    elif "pdf" in geo_src:
        conf, basis = 0.55, "PDF geometry"
        needs_dxf = True
        pdf_reason = (
            "geometry read from PDF vectors rather than a flat pattern, so the cut profile and "
            "blank are approximate"
        )
    else:
        conf, basis = 0.50, "geometry basis unclear"

    # bought-in price book confidence overrides geometry basis for catalogue lines
    cost_src = str(part.get("cost_source") or "").lower()
    pb_conf = part.get("price_confidence")
    is_bought_in = False
    if pb_conf is not None and ("price_book" in cost_src or "manual_estimate" in cost_src
                                or "catalogue" in cost_src):
        conf, basis = _f(pb_conf), "bought-in priced from historical/manual price book"
        provisos.extend(part.get("price_provisos") or [])
        is_bought_in = True

    # When a fabricated line has no flat DXF, make the flag actionable: state briefly WHY the
    # PDF alone was not enough, then name the exact flat DXF to request next. Sits alongside the
    # low-confidence flag in the Decision Report so the request is explicit, not implied.
    if needs_dxf and not is_bought_in:
        if pdf_reason:
            provisos.append(f"PDF alone insufficient: {pdf_reason}")
        _pn = str(part.get("part_number") or part.get("item_number") or "this part").strip()
        _rev = str(part.get("revision") or part.get("drawing_revision") or "").strip()
        _rev_txt = f" rev {_rev}" if _rev and _rev.upper() not in ("", "NONE") else ""
        provisos.append(
            f"ACTION \u2014 request flat DXF for {_pn}{_rev_txt} (one flat pattern per part) "
            "to replace inferred geometry and lift confidence"
        )

    # material signal — only meaningful for fabricated parts, not bought-ins
    if not is_bought_in:
        mat = str(part.get("normalized_material") or "").upper()
        mat_src = str(part.get("material_source") or "").lower()
        if not mat or mat in ("UNKNOWN", "NONE", "LED", "?"):
            conf -= 0.30
            provisos.append("material not extracted — price manually / confirm")
        elif mat_src and ("inferred" in mat_src or "suffix" in mat_src or "family" in mat_src):
            conf -= 0.10
            provisos.append(f"material inferred ({mat_src}), not declared on drawing")

    # absorb the learning-engine flag (#2)
    flag = part.get("_learning_flag")
    if flag:
        conf -= 0.15
        provisos.append(f"learning flag: {flag}")

    # calibration delta (#1) feeds confidence
    if calib_line:
        d = calib_line.get("direction")
        if d in ("over", "under"):
            conf -= 0.20
            provisos.extend(calib_line.get("provisos") or [])
        elif d == "close":
            conf = min(conf + 0.05, 0.95)
        elif d == "no_ground_truth":
            conf -= 0.05
            provisos.append("no historical comparator — unvalidated")

    conf = max(0.10, min(conf, 0.95))
    return {
        "confidence_pct": round(conf * 100),
        "basis": basis,
        "provisos": _dedupe_provisos(provisos),
    }


def _dedupe_provisos(items: List[str]) -> List[str]:
    seen, out = set(), []
    for s in items:
        s = str(s).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def job_confidence(parts: List[Dict[str, Any]]) -> Optional[int]:
    """Cost-weighted average of per-line confidence — the job headline %."""
    num = den = 0.0
    for p in parts:
        c = p.get("confidence_pct")
        if c is None:
            continue
        w = max(_f(p.get("extended_estimate") or p.get("unit_estimate")), 0.01)
        num += c * w
        den += w
    return round(num / den) if den else None


def annotate_summary(
    summary: Dict[str, Any],
    historical_rows: Optional[List[Dict[str, Any]]] = None,
    conn: Any = None,
    tol: float = 0.15,
) -> Dict[str, Any]:
    """The single pipeline call. Stamps each part with confidence_pct /
    confidence_basis / provisos, and the summary with calibration_scorecard and
    job_confidence_pct, so the Decision Report can render them. Never raises;
    with no ground truth it still scores confidence from the other signals.

    Call in main.py AFTER post_scan and BEFORE write_estimate_xlsx.
    """
    mw = summary.get("manufacturing_writeup") or {}
    parts = mw.get("parts") or []
    if not parts:
        return {"lines": [], "summary": {}}

    rows = historical_rows
    if rows is None and conn is not None:
        try:
            pns = [p.get("part_number") for p in parts if p.get("part_number")]
            rows = fetch_historical_rows(conn, pns)
        except Exception:
            rows = []
    rows = rows or []

    scorecard = build_scorecard(parts, rows, tol=tol)
    line_by_pn = {l["part_number"]: l for l in scorecard["lines"]}
    for p in parts:
        cp = line_confidence_and_provisos(p, line_by_pn.get(p.get("part_number")))
        p["confidence_pct"] = cp["confidence_pct"]
        p["confidence_basis"] = cp["basis"]
        p["provisos"] = cp["provisos"]

    summary["calibration_scorecard"] = scorecard["summary"]
    summary["job_confidence_pct"] = job_confidence(parts)
    return scorecard


# ══════════════════════════════════════════════════════════════════════════════
# 3. DEAD-OVERRIDE FINDER  (check whether the LED seed rules still fire)
# ══════════════════════════════════════════════════════════════════════════════

def find_dead_overrides(
    overrides: List[Dict[str, Any]], stale_if_never_fired: bool = True
) -> List[Dict[str, Any]]:
    """Given get_active_overrides() output, list rules that look superseded:
    never fired, or fired zero times. Use to confirm the LED seed rules went
    dead after the page-collision / MATERIAL-authority fixes. Returns candidates
    for Active=0 (keep the row for audit; just stop applying it)."""
    dead = []
    for o in overrides or []:
        name = o.get("RuleName") or o.get("rule_name") or ""
        fired = o.get("TriggerCount", o.get("trigger_count", 0)) or 0
        last = o.get("LastFired") or o.get("last_fired")
        if (fired == 0) and (stale_if_never_fired or last is None):
            dead.append({"rule_name": name, "trigger_count": fired, "last_fired": last,
                         "recommend": "Active=0 (superseded by structural fix; keep for audit)"})
    return dead


# ══════════════════════════════════════════════════════════════════════════════
# 4. SOURCE-OVERLAP TEST  (price book vs HistoricalEstimates)
# ══════════════════════════════════════════════════════════════════════════════

def _hist_unit_by_code(historical_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Map a leading catalogue code in a historical description/PN to a unit cost."""
    out: Dict[str, List[float]] = {}
    code_re = re.compile(r"^\s*([A-Z]+\d*)\b")
    for r in historical_rows or []:
        text = str(r.get("PartNumber") or r.get("Description") or "")
        m = code_re.match(text.upper())
        uc = _f(r.get("UnitCost"))
        if m and uc > 0:
            out.setdefault(m.group(1), []).append(uc)
    return {k: round(sum(v) / len(v), 4) for k, v in out.items()}


def compare_price_sources(
    price_book: Dict[str, Dict[str, Any]],
    historical_rows: List[Dict[str, Any]],
    order_qty: int = 100,
    tol: float = 0.15,
) -> Dict[str, Any]:
    """Test the overlap between the spreadsheet price book and HistoricalEstimates
    so we can pick one source of truth. Reports codes in both (with price
    agreement), and codes unique to each."""
    hist = _hist_unit_by_code(historical_rows)
    book_codes = {rec.get("code", "").upper(): rec for rec in price_book.values()
                  if rec.get("code")}

    in_both, disagree = [], []
    for code, rec in book_codes.items():
        if code in hist:
            pb = rec["prices_by_qty"].get(order_qty)
            if pb is None and rec["prices_by_qty"]:
                pb = list(rec["prices_by_qty"].values())[0]
            h = hist[code]
            agree = (pb is not None and h > 0 and abs(pb - h) / h <= tol)
            entry = {"code": code, "price_book": pb, "historical": h, "agree": agree}
            in_both.append(entry)
            if not agree:
                disagree.append(entry)
    return {
        "codes_in_both": in_both,
        "price_disagreements": disagree,
        "only_in_price_book": sorted(set(book_codes) - set(hist)),
        "only_in_historical": sorted(set(hist) - set(book_codes)),
        "verdict": (
            "sources overlap — pick one as canonical (price book keeps qty breaks)"
            if in_both else
            "little/no overlap — keep both, they cover different items"
        ),
    }
