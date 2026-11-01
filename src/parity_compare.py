#!/usr/bin/env python3
r"""parity_compare.py — the AI estimate against the manual one, line by line (SCRUM-157, D-623).

JG, 1 Nov 2026: the parity "we have built in which is file by file ... will be very old and
needing a big upgrade in quality now that we have all of the information and quality of data".
The review: "distinguish cost from selling price, match quantities and revisions, and expose
differences in scope, delivery, installation, overheads and margin. The manual estimate is a
comparison — not automatically the correct answer."

BOTH SIDES ARE THE SAME HOUSE TEMPLATE. The estimator's sheet and the engine's workbook are the
one SDI Estimate sheet, so each is read the same way: the material blocks and the labour table
by the template's own header maps (parity_check, which takes them from the read-back), the price
chain by its labels. The engine's side is its read-back, final_estimate: the rows as Excel
calculated them, each with the cell it was charged in.

WHAT IS COMPARED, AND KEPT APART
  * HOW EACH SIDE ADDS UP. Each side's lines against its own labelled totals, first. A
    comparison of a parse that dropped rows is a comparison of the parser.
  * THE COST BUILD-UP: material, labour, the rebate, the overhead absorption, and the total
    unit cost, each with its cell. Cost is never compared with a selling price.
  * THE SELLING SIDE: margin and sell price, compared only with each other.
  * COMMERCIAL LINES: delivery, packaging and installation, wherever either sheet carries
    them, in the materials or the labour. Every line on the manual sheet is listed with its AI
    counterpart or "not in the AI estimate", and the reverse.
  * SCOPE, PART BY PART: in one estimate and not the other; made on one and bought on the
    other (the block it sits in says which); quantity per unit; material not charged where the
    part is worked; and the inputs behind a money difference (blank, gauge, nest).
  * LABOUR BY DEPARTMENT, set-up apart from run.
  * QUANTITIES. The sheet's figures are per unit at its own quantity. When the two quantities
    differ, the AI unit cost is taken at the manual's quantity from the run's own quantity
    sweep where it priced it; otherwise the unit costs are marked not comparable, and every
    line says the quantities differ.
  * REVISIONS: the drawing revision each side estimated, and whether they differ.

Differences are reported as differences, AI against manual, signed. A verdict word says how far
apart the two are, not which is right.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import parity_check as pc  # noqa: E402

SCHEMA = "sdi_parity_detail.v1"
BLOCK_KIND = {"bom": "bought", "tube": "made", "steel": "made", "other_sheet": "made"}
BLOCK_NAME = {"bom": "Bill of materials", "tube": "Wire and tube", "steel": "Sheet steel",
              "other_sheet": "Other sheet material"}

COMMERCIAL = (
    ("delivery", "Delivery and carriage", re.compile(
        r"\b(deliver\w*|carriage|freight|haulage|transport\w*|courier\w*|shipp\w*|postage|"
        r"lorry|artic|distribution)\b", re.I)),
    ("packaging", "Packaging", re.compile(
        r"\b(packag\w*|packing|pack|cartons?|boxe?s?|crates?|pallets?|skids?|wrap\w*|foam|"
        r"bubble|shrink\w*|void ?fill)\b", re.I)),
    ("installation", "Installation and site work", re.compile(
        r"\b(install\w*|on[- ]site|site (?:work|fit\w*|survey|visit)|fitters?|"
        r"surveys?|commission\w*)\b", re.I)),
)


def _f(v: Any) -> Optional[float]:
    return pc._f(v)


def _thresholds() -> Tuple[float, float]:
    try:
        import config
        t = (getattr(config, "WORKBOOK_EQUIVALENT_PRICING", {}) or {}).get(
            "variance_thresholds_pct") or {}
        return float(t.get("match", 3.0)), float(t.get("warning", 10.0))
    except Exception:                                                # noqa: BLE001
        return 3.0, 10.0


def _compare(ai: Optional[float], manual: Optional[float]) -> Dict[str, Any]:
    """AI against manual: the signed difference, its percentage of the manual figure, and how
    far apart that is. Missing is missing, never zero."""
    if ai is None or manual is None:
        return {"delta": None, "pct": None, "status": "not read"}
    delta = round(ai - manual, 2)
    if abs(manual) < 1e-9:
        return {"delta": delta, "pct": None, "status": "match" if abs(delta) < 0.005 else "review"}
    pct = round((ai - manual) / abs(manual) * 100.0, 1)
    match, warn = _thresholds()
    status = "match" if abs(pct) <= match else "warning" if abs(pct) <= warn else "fail"
    return {"delta": delta, "pct": pct, "status": status}


def _norm_rev(v: Any) -> str:
    t = re.sub(r"^(rev(ision)?|iss(ue)?)\s*\.?\s*", "", str(v or "").strip(), flags=re.I)
    t = t.strip().upper()
    return t.lstrip("0") or ("0" if t else "")


_ISSUE_IN_NAME = re.compile(r"\b(?:ISS(?:UE)?|REV(?:ISION)?)\s*\.?\s*([0-9]+|[A-Z])\b", re.I)


# ── reading ─────────────────────────────────────────────────────────────────────────────

def _right_of(grid: List[List[Any]], starts: Iterable[str], *, numeric: bool = True,
              label_cols: int = 16) -> Tuple[Any, Optional[str]]:
    """The first value to the right of a label that starts with one of `starts`, and its cell."""
    needles = tuple(s.lower() for s in starts)
    for r, row in enumerate(grid):
        for c in range(min(len(row), label_cols)):
            text = str(row[c] or "").strip().lower()
            if not text or not text.startswith(needles):
                continue
            for cc in range(c + 1, len(row)):
                v = row[cc]
                if v in (None, ""):
                    continue
                if numeric:
                    fv = _f(v)
                    if fv is None:
                        continue
                    return fv, pc._a1(r, cc)
                return v, pc._a1(r, cc)
    return None, None


def read_manual(path: str | Path) -> Dict[str, Any]:
    """The estimator's sheet: its blocks and labour rows with their cells, its price chain and
    its header."""
    p = Path(path)
    side = pc.read_house_workbook(p)
    grid = pc._open_rows(p)
    cells = dict(side.get("total_cells") or {})
    chain: Dict[str, Any] = {}
    for key, labels in (("material", ("total material cost",)),
                        ("labour", ("total labour cost",)),
                        ("unit", ("total unit cost",)),
                        ("rebate", ("rebate calculator", "rebate")),
                        ("margin", ("margin applied", "margin")),
                        ("sell", ("sell price", "selling price"))):
        v, cell = _right_of(grid, labels)
        if key in ("material", "labour", "unit") and side["totals"].get(key) is not None:
            v, cell = side["totals"][key], cells.get(key, cell)
        chain[key] = {"value": v, "cell": cell}
    m = chain["margin"]["value"]
    if isinstance(m, (int, float)) and m > 1:
        chain["margin"]["value"] = round(m / 100.0, 6)
        chain["margin"]["note"] = "entered as a percentage"
    r = chain["rebate"]["value"]
    if isinstance(r, (int, float)) and r > 1:
        chain["rebate"]["value"] = round(r / 100.0, 6)
    head: Dict[str, Any] = {}
    for key, labels, numeric in (("drawing", ("drawing no",), False), ("revision", ("rev",), False),
                                 ("customer", ("customer",), False),
                                 ("quantity", ("quantity",), True)):
        v, cell = _right_of(grid, labels, numeric=numeric, label_cols=6)
        head[key] = {"value": v, "cell": cell}
    if head["quantity"]["value"] is None and (side.get("headline") or {}).get("quantity"):
        head["quantity"]["value"] = side["headline"]["quantity"]
    rev = head["revision"]["value"]
    if rev in (None, ""):
        m2 = _ISSUE_IN_NAME.findall(p.stem)
        if m2:
            head["revision"] = {"value": m2[-1], "cell": None, "note": "from the file name"}
    side.update(path=str(p), chain=chain, head=head, kind="manual")
    side["headline"] = {"quantity": head["quantity"]["value"]}
    return side


def _ai_revision(doc: Dict[str, Any], drawing: str) -> Optional[str]:
    es = doc.get("estimate_summary") if isinstance(doc.get("estimate_summary"), dict) else {}
    for holder in (doc, es, doc.get("title_block") or {}, es.get("title_block") or {}):
        for k in ("drawing_revision", "revision"):
            v = (holder or {}).get(k) if isinstance(holder, dict) else None
            if v not in (None, "") and not isinstance(v, (dict, list)):
                return str(v)
    want = pc._key(drawing) if drawing else ""
    for part in (es.get("part_estimates") or doc.get("parts") or []):
        if not isinstance(part, dict):
            continue
        if want and pc._key(part.get("part_number")) == want:
            v = part.get("revision") or part.get("drawing_revision")
            if v:
                return str(v)
    return None


def read_ai(summary_path: str | Path) -> Dict[str, Any]:
    """The engine's side: its read-back rows with their charged cells, its price chain, its
    quantity and quantity sweep, and the revision it estimated."""
    p = Path(summary_path)
    doc = json.loads(p.read_text(encoding="utf-8"))
    side = pc.read_engine_json(p)
    es = doc.get("estimate_summary") if isinstance(doc.get("estimate_summary"), dict) else {}
    wep = es.get("workbook_equivalent_pricing") or {}
    fe = doc.get("final_estimate") if isinstance(doc.get("final_estimate"), dict) else \
        (es.get("final_estimate") if isinstance(es.get("final_estimate"), dict) else {})
    comp = (fe or {}).get("unit_price_composition") or {}
    totals = side.get("totals") or {}
    unit = totals.get("unit")
    if unit is None:
        unit = _f(wep.get("l105_total_unit_cost_gbp") or wep.get("m105_total_unit_cost_gbp"))
    chain = {
        "material": {"value": totals.get("material"), "source": "final_estimate totals"},
        "labour": {"value": totals.get("labour"), "source": "final_estimate totals"},
        "unit": {"value": unit, "cell": ((fe or {}).get("totals") or {}).get("unit_cell"),
                 "source": "final_estimate totals"},
        "rebate": {"value": _f(comp.get("rebate_fraction"))
                   if comp.get("rebate_fraction") is not None else _f(wep.get("m107_rebate_fraction")),
                   "source": "the unit cell's formula" if comp.get("rebate_fraction") is not None
                   else "workbook_equivalent_pricing"},
        "absorption": {"value": _f(comp.get("absorption_divisor"))
                       if comp.get("absorption_divisor") is not None
                       else _f(wep.get("overhead_absorption_factor")),
                       "source": "the unit cell's formula" if comp.get("absorption_divisor")
                       else "workbook_equivalent_pricing"},
        "margin": {"value": _f(wep.get("m109_sell_margin_fraction")),
                   "source": "workbook_equivalent_pricing"},
        "sell": {"value": _f(wep.get("l111_sell_price_gbp")), "source": "workbook_equivalent_pricing"},
    }
    qty = _f(((es.get("estimate_workbook_inputs") or {}).get("assumed_job_quantity")))
    sweep = {}
    for row in ((doc.get("quantity_sweep") or {}).get("rows") or []):
        q, u = _f((row or {}).get("quantity")), _f((row or {}).get("unit"))
        if q and u:
            sweep[q] = u
    drawing = str(doc.get("drawing_number") or es.get("drawing_number") or "")
    side.update(path=str(p), chain=chain, kind="ai", sweep=sweep,
                head={"drawing": {"value": drawing or None},
                      "revision": {"value": _ai_revision(doc, drawing)},
                      "quantity": {"value": qty}})
    side["headline"] = {"quantity": qty}
    return side


# ── sections ────────────────────────────────────────────────────────────────────────────

def _commercial_category(text: str) -> Optional[Tuple[str, str]]:
    for key, label, rx in COMMERCIAL:
        if rx.search(text or ""):
            return key, label
    return None


def _material_lines(side: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for block in pc.BLOCK_ORDER:
        for line in side["blocks"].get(block, []) or []:
            out.append({**line, "block": block})
    return out


def _cell_of(line: Dict[str, Any]) -> Optional[str]:
    c = line.get("cell") or line.get("charged_cell")
    return str(c).replace("Estimate!", "") if c else None


def commercial_lines(manual: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    """Every delivery, packaging and installation line on either sheet, paired by kind."""
    def collect(side):
        found = []
        for line in _material_lines(side):
            if line["block"] != "bom":
                continue                    # a fabricated part is never a commercial line
            text = f"{line.get('code') or ''} {line.get('description') or ''}"
            cat = _commercial_category(text)
            if cat:
                found.append({"category": cat[0], "label": cat[1], "where": "materials",
                              "description": str(line.get("description") or line.get("code") or ""),
                              "gbp": _f(line.get("total_value_gbp")), "cell": _cell_of(line),
                              "code": line.get("code")})
        for row in side.get("labour_rows") or []:
            text = " ".join(str(row.get(k) or "") for k in ("operation", "description", "department"))
            cat = _commercial_category(text)
            if cat:
                found.append({"category": cat[0], "label": cat[1], "where": "labour",
                              "description": str(row.get("operation") or row.get("description") or ""),
                              "gbp": _f(row.get("total_value_gbp")), "cell": _cell_of(row),
                              "department": row.get("department")})
        return found
    m_lines, a_lines = collect(manual), collect(ai)
    categories = []
    for key, label, _rx in COMMERCIAL:
        ms = [x for x in m_lines if x["category"] == key]
        as_ = [x for x in a_lines if x["category"] == key]
        if not ms and not as_:
            continue
        m_tot = round(sum(x["gbp"] or 0 for x in ms), 2) if ms else None
        a_tot = round(sum(x["gbp"] or 0 for x in as_), 2) if as_ else None
        categories.append({"category": key, "label": label, "manual": m_tot, "ai": a_tot,
                           **_compare(a_tot, m_tot),
                           "presence": "both" if ms and as_ else ("manual only" if ms else "AI only"),
                           "manual_lines": ms, "ai_lines": as_})
    listing = []
    for x in m_lines:
        counterpart = [a for a in a_lines if a["category"] == x["category"]]
        listing.append({**x, "side": "manual",
                        "counterpart": counterpart or None,
                        "note": None if counterpart else "not in the AI estimate"})
    for a in a_lines:
        if not any(m["category"] == a["category"] for m in m_lines):
            listing.append({**a, "side": "AI", "counterpart": None,
                            "note": "not on the manual sheet"})
    return {"categories": categories, "lines": listing}


def _commercial_codes(side: Dict[str, Any]) -> set:
    out = set()
    for line in _material_lines(side):
        if line["block"] == "bom" and _commercial_category(
                f"{line.get('code') or ''} {line.get('description') or ''}"):
            out.add(line.get("code"))
    return out


def _labour_by_part(side: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for row in side.get("labour_rows") or []:
        raw = str(row.get("part_numbers") or "").strip()
        if not raw:
            continue
        for token in re.split(r"[,;/\s]+", raw):
            code = pc._key(token)
            if code:
                out[code] = round(out.get(code, 0.0) + (_f(row.get("total_value_gbp")) or 0.0), 2)
    return out


_INPUTS = [("length_mm", "blank length", 1.0), ("width_mm", "blank width", 1.0),
           ("gauge", "gauge", 0.01), ("thickness_mm", "thickness", 0.01),
           ("qty_per_sheet", "parts per sheet", 0.01)]


def scope(manual: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    """Every part on either side: in both or one, made or bought, quantity per unit, material
    charged or not, the money and the inputs behind it."""
    skip = _commercial_codes(manual) | _commercial_codes(ai)

    def index(side):
        idx: Dict[str, Dict[str, Any]] = {}
        for line in _material_lines(side):
            code = line.get("code") or pc._lead_code(line.get("description"))
            if not code or code in skip:
                continue
            node = idx.setdefault(code, {"blocks": [], "gbp": 0.0, "cells": [], "qty": None,
                                         "description": "", "inputs": {}})
            if line["block"] not in node["blocks"]:
                node["blocks"].append(line["block"])
            node["gbp"] = round(node["gbp"] + (_f(line.get("total_value_gbp")) or 0.0), 2)
            if _cell_of(line):
                node["cells"].append(_cell_of(line))
            if node["qty"] is None:
                node["qty"] = _f(line.get("qty_per_unit"))
            node["description"] = node["description"] or str(line.get("description") or "")
            for field, _label, _tol in _INPUTS:
                if field not in node["inputs"] and _f(line.get(field)) is not None:
                    node["inputs"][field] = _f(line.get(field))
        return idx

    def kind(node):
        if not node:
            return None
        kinds = {BLOCK_KIND.get(b, "made") for b in node["blocks"]}
        return "made and bought" if len(kinds) > 1 else kinds.pop()

    m_idx, a_idx = index(manual), index(ai)
    m_lab, a_lab = _labour_by_part(manual), _labour_by_part(ai)
    codes = sorted(set(m_idx) | set(a_idx) | ({c for c in m_lab if c in a_idx}
                                               | {c for c in a_lab if c in m_idx}))
    rows = []
    for code in codes:
        m, a = m_idx.get(code), a_idx.get(code)
        desc = str((a or m or {}).get("description") or "")
        if desc.upper().startswith(code.upper()):
            desc = desc[len(code):].strip(" -")
        row: Dict[str, Any] = {
            "code": code, "description": desc[:80],
            "manual": {"gbp": m["gbp"] if m else None, "blocks": m["blocks"] if m else [],
                       "kind": kind(m), "qty": m["qty"] if m else None,
                       "cells": m["cells"] if m else [], "labour_gbp": m_lab.get(code)},
            "ai": {"gbp": a["gbp"] if a else None, "blocks": a["blocks"] if a else [],
                   "kind": kind(a), "qty": a["qty"] if a else None,
                   "cells": a["cells"] if a else [], "labour_gbp": a_lab.get(code)},
        }
        row.update(_compare(row["ai"]["gbp"], row["manual"]["gbp"]))
        row["only_on"] = None if (m and a) else ("manual" if m else "AI")
        row["made_bought_differs"] = bool(m and a and kind(m) != kind(a))
        mq, aq = row["manual"]["qty"], row["ai"]["qty"]
        row["qty_differs"] = bool(mq is not None and aq is not None and abs(mq - aq) > 0.01)
        # MATERIAL NOT CHARGED: worked on one side (labour, or a made line at nothing) with no
        # material money, while the other side charges material for the same part.
        row["material_not_charged_on"] = None
        for side_name, mine, other, lab in (("AI", a, m, a_lab), ("manual", m, a, m_lab)):
            mine_gbp = (mine or {}).get("gbp") or 0.0
            other_gbp = (other or {}).get("gbp") or 0.0
            worked = code in lab or bool(mine)
            if worked and mine_gbp <= 0.005 and other_gbp > 0.005:
                row["material_not_charged_on"] = side_name
                break
        inputs = []
        if m and a:
            for field, label, tol in _INPUTS:
                mv, av = m["inputs"].get(field), a["inputs"].get(field)
                if mv is not None and av is not None and abs(mv - av) > tol:
                    inputs.append({"field": label, "manual": mv, "ai": av})
        row["inputs"] = inputs
        row["flagged"] = bool(row["only_on"] or row["made_bought_differs"] or row["qty_differs"]
                              or row["material_not_charged_on"] or inputs
                              or row["status"] in ("warning", "fail"))
        rows.append(row)
    rows.sort(key=lambda r: (not r["flagged"], -abs(r["delta"] or (r["manual"]["gbp"] or 0)
                                                     or (r["ai"]["gbp"] or 0))))
    return {"parts": rows, "counts": {
        "parts": len(rows), "in_both": sum(1 for r in rows if not r["only_on"]),
        "manual_only": sum(1 for r in rows if r["only_on"] == "manual"),
        "ai_only": sum(1 for r in rows if r["only_on"] == "AI"),
        "made_bought_differs": sum(1 for r in rows if r["made_bought_differs"]),
        "qty_differs": sum(1 for r in rows if r["qty_differs"]),
        "material_not_charged": sum(1 for r in rows if r["material_not_charged_on"]),
    }}


def quantity(manual: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    mq = _f(manual["head"]["quantity"]["value"])
    aq = _f(ai["head"]["quantity"]["value"])
    out: Dict[str, Any] = {"manual": mq, "ai": aq, "comparable": True, "compared_at": mq or aq,
                           "note": "", "manual_cell": manual["head"]["quantity"].get("cell")}
    if mq is None or aq is None:
        out["note"] = ("One side's quantity could not be read; the figures are compared as "
                       "they stand. Check the quantity on both before relying on them.")
        return out
    if abs(mq - aq) < 1e-9:
        return out
    sweep = ai.get("sweep") or {}
    if mq in sweep:
        out.update(ai_unit_at_manual_qty=round(sweep[mq], 2), compared_at=mq, note=(
            f"The AI run priced {aq:g} off and the manual sheet {mq:g} off. The unit cost is "
            f"compared at {mq:g} off from the run's own quantity sweep; the lines below are at "
            f"each side's own quantity."))
        return out
    out.update(comparable=False, compared_at=None, note=(
        f"Quantities differ: the AI run priced {aq:g} off and the manual sheet is {mq:g} off, "
        f"which the run did not price. Unit costs and lines are not like for like; re-run the "
        f"estimate at {mq:g} off to compare them."))
    return out


def cost_build(manual: Dict[str, Any], ai: Dict[str, Any], qty: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Material, labour, the uplift between them and the unit cost (rebate and overhead
    absorption), and the total unit cost: cost only, never a selling price."""
    mc, ac = manual["chain"], ai["chain"]

    def val(chain, key):
        return _f((chain.get(key) or {}).get("value"))

    rows = []
    for key, label in (("material", "Total material cost"), ("labour", "Total labour cost")):
        m, a = val(mc, key), val(ac, key)
        rows.append({"key": key, "label": label, "manual": m, "ai": a, **_compare(a, m),
                     "manual_cell": (mc.get(key) or {}).get("cell"),
                     "ai_source": (ac.get(key) or {}).get("source")})
    # The uplift: rebate and overhead absorption, the difference between the subtotals and
    # the unit cost on each side's own sheet.
    m_unit, a_unit = val(mc, "unit"), val(ac, "unit")
    m_sub = (val(mc, "material") or 0) + (val(mc, "labour") or 0)
    a_sub = (val(ac, "material") or 0) + (val(ac, "labour") or 0)
    m_up = round(m_unit - m_sub, 2) if m_unit is not None and m_sub else None
    a_up = round(a_unit - a_sub, 2) if a_unit is not None and a_sub else None
    rows.append({"key": "overheads", "label": "Rebate and overhead absorption", "manual": m_up,
                 "ai": a_up, **_compare(a_up, m_up),
                 "note": "the unit cost less material and labour, on each side's own sheet"})
    m_reb, a_reb = val(mc, "rebate"), val(ac, "rebate")
    rows.append({"key": "rebate", "label": "Customer rebate (fraction)", "manual": m_reb,
                 "ai": a_reb, "delta": (round(a_reb - m_reb, 4) if m_reb is not None
                                        and a_reb is not None else None),
                 "pct": None, "status": ("match" if m_reb is not None and a_reb is not None
                                         and abs(a_reb - m_reb) < 1e-6 else
                                         "not read" if m_reb is None or a_reb is None else "warning"),
                 "manual_cell": (mc.get("rebate") or {}).get("cell"), "fraction": True})
    m_div = None
    if m_unit and m_sub and m_reb is not None and m_unit > 0:
        m_div = round(m_sub / ((1.0 - m_reb) * m_unit), 4)
    a_div = val(ac, "absorption")
    rows.append({"key": "absorption", "label": "Overhead absorption divisor", "manual": m_div,
                 "ai": a_div, "delta": (round(a_div - m_div, 4) if m_div is not None
                                        and a_div is not None else None),
                 "pct": None, "status": ("match" if m_div is not None and a_div is not None
                                         and abs(a_div - m_div) < 0.0015 else
                                         "not read" if m_div is None or a_div is None else "warning"),
                 "note": "the manual side's divisor is worked back from its own figures",
                 "fraction": True, "divisor": True})
    a_cmp = qty.get("ai_unit_at_manual_qty", a_unit)
    unit_row = {"key": "unit", "label": "Total unit cost", "manual": m_unit, "ai": a_cmp,
                **_compare(a_cmp, m_unit), "manual_cell": (mc.get("unit") or {}).get("cell"),
                "ai_source": (ac.get("unit") or {}).get("source")}
    if "ai_unit_at_manual_qty" in qty:
        unit_row["note"] = f"AI at {qty['compared_at']:g} off from its quantity sweep"
    if not qty.get("comparable", True):
        unit_row.update(status="quantities differ", note=qty["note"])
    rows.append(unit_row)
    if not qty.get("comparable", True):
        for r in rows[:3]:
            r["note"] = (r.get("note") + "; " if r.get("note") else "") + "quantities differ"
    return rows


def selling(manual: Dict[str, Any], ai: Dict[str, Any],
            qty: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Margin and sell price, compared only with each other, at the same quantity rule as the
    unit cost: at another quantity the AI sell price is its swept unit cost at the manual's
    quantity over its own margin, or the two are not comparable."""
    qty = qty or {}
    mc, ac = manual["chain"], ai["chain"]
    m_mar, a_mar = _f(mc["margin"]["value"]), _f(ac["margin"]["value"])
    m_sell, a_sell = _f(mc["sell"]["value"]), _f(ac["sell"]["value"])
    sell_note = None
    if qty.get("ai_unit_at_manual_qty") is not None:
        if a_mar is not None and a_mar < 1:
            a_sell = round(qty["ai_unit_at_manual_qty"] / (1.0 - a_mar), 2)
            sell_note = f"AI at {qty['compared_at']:g} off: its swept unit cost over its margin"
        else:
            a_sell, sell_note = None, "the AI margin was not read, so its sell price at the manual's quantity cannot be worked out"
    rows = [{"key": "margin", "label": "Margin (fraction of sell)", "manual": m_mar, "ai": a_mar,
             "delta": round(a_mar - m_mar, 4) if m_mar is not None and a_mar is not None else None,
             "pct": None, "fraction": True,
             "status": ("match" if m_mar is not None and a_mar is not None and abs(a_mar - m_mar) < 1e-6
                        else "not read" if m_mar is None or a_mar is None else "warning"),
             "manual_cell": mc["margin"].get("cell"),
             "note": ("the engine leaves margin for the estimator to set" if a_mar in (None, 0.0)
                      else None)},
            {"key": "sell", "label": "Sell price", "manual": m_sell, "ai": a_sell,
             **_compare(a_sell, m_sell), "manual_cell": mc["sell"].get("cell"),
             "ai_source": ac["sell"].get("source")}]
    if sell_note:
        rows[1]["note"] = sell_note
    if not qty.get("comparable", True):
        rows[1].update(status="quantities differ", note=qty.get("note"))
    return rows


def revision(manual: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    m = manual["head"]["revision"]
    a = ai["head"]["revision"]
    mv, av = _norm_rev(m.get("value")), _norm_rev(a.get("value"))
    return {"manual": m.get("value"), "manual_note": m.get("note"), "ai": a.get("value"),
            "differs": bool(mv and av and mv != av),
            "note": ("" if (mv and av) else "One side's revision is not recorded; check the "
                                            "drawing each estimate was made from.")}


def _differences(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in detail["cost_build"] + detail["selling"]:
        if r["status"] in ("warning", "fail", "quantities differ") and not r.get("fraction"):
            out.append({"kind": "cost" if r in detail["cost_build"] else "selling",
                        "what": r["label"], "delta_gbp": r["delta"], "pct": r["pct"],
                        "anchor": f"line-{r['key']}"})
        elif r.get("fraction") and r["status"] == "warning":
            out.append({"kind": "terms", "what": r["label"], "delta_gbp": None, "pct": None,
                        "detail": f"manual {r['manual']} against AI {r['ai']}",
                        "anchor": f"line-{r['key']}"})
    for c in detail["commercial"]["categories"]:
        if c["presence"] != "both" or c["status"] in ("warning", "fail"):
            out.append({"kind": "commercial", "what": c["label"] + (
                f" ({c['presence']})" if c["presence"] != "both" else ""),
                "delta_gbp": c["delta"] if c["presence"] == "both" else
                (c["ai"] or 0) - (c["manual"] or 0), "pct": c["pct"],
                "anchor": f"commercial-{c['category']}"})
    for p in detail["scope"]["parts"]:
        if not p["flagged"]:
            continue
        why = []
        if p["only_on"]:
            why.append(f"only on the {p['only_on']} estimate")
        if p["made_bought_differs"]:
            why.append(f"{p['manual']['kind']} on the manual, {p['ai']['kind']} on the AI")
        if p["material_not_charged_on"]:
            why.append(f"material not charged on the {p['material_not_charged_on']} estimate")
        if p["qty_differs"]:
            why.append(f"quantity per unit {p['manual']['qty']:g} against {p['ai']['qty']:g}")
        if p["inputs"]:
            why.append(", ".join(f"{i['field']} {i['manual']:g} against {i['ai']:g}" for i in p["inputs"][:2]))
        delta = p["delta"] if p["delta"] is not None else (p["ai"]["gbp"] or 0) - (p["manual"]["gbp"] or 0)
        out.append({"kind": "scope", "what": f"{p['code']} {p['description'][:40]}".strip(),
                    "detail": "; ".join(why) or "money differs", "delta_gbp": round(delta, 2),
                    "pct": p["pct"], "anchor": f"part-{_slug(p['code'])}",
                    "structural": bool(p["made_bought_differs"] or p["material_not_charged_on"]
                                       or p["only_on"])})
    for d in detail["labour"]["rows"]:
        if abs(d["delta"]) >= max(1.0, 0.1 * max(abs(d["manual"]), abs(d["engine"]))):
            out.append({"kind": "labour", "what": f"Labour, {d['department']}",
                        "delta_gbp": d["delta"], "pct": None,
                        "anchor": f"dept-{_slug(d['department'])}"})
    structural = [x for x in out if x.get("structural")]
    rest = sorted([x for x in out if not x.get("structural")],
                  key=lambda x: -abs(x.get("delta_gbp") or 0))
    return sorted(structural, key=lambda x: -abs(x.get("delta_gbp") or 0))[:15] + rest[:20]


def _slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "x"


def compare(summary_path: str | Path, manual_path: str | Path) -> Dict[str, Any]:
    """The whole comparison, as one record."""
    manual = read_manual(manual_path)
    ai = read_ai(summary_path)
    qty = quantity(manual, ai)
    detail: Dict[str, Any] = {
        "schema": SCHEMA,
        "manual": {"path": manual["path"], "head": manual["head"], "problems": manual["problems"],
                   "reconcile": pc.reconcile(manual)},
        "ai": {"path": ai["path"], "head": ai["head"], "basis": ai.get("basis"),
               "problems": ai["problems"], "reconcile": pc.reconcile(ai)},
        "quantity": qty, "revision": revision(manual, ai),
        "cost_build": cost_build(manual, ai, qty), "selling": selling(manual, ai, qty),
        "commercial": commercial_lines(manual, ai), "scope": scope(manual, ai),
        "labour": pc.compare_labour(manual, ai),
        "thresholds_pct": dict(zip(("match", "warning"), _thresholds())),
    }
    unit = next(r for r in detail["cost_build"] if r["key"] == "unit")
    sell = next(r for r in detail["selling"] if r["key"] == "sell")
    detail["headline"] = {
        "ai_unit_cost_gbp": unit["ai"], "manual_unit_cost_gbp": unit["manual"],
        "gap_gbp": unit["delta"], "pct": unit["pct"], "status": unit["status"],
        "compared_at_qty": qty.get("compared_at"), "comparable": qty.get("comparable", True),
        "ai_sell_gbp": sell["ai"], "manual_sell_gbp": sell["manual"],
        "reconciles": {"manual": detail["manual"]["reconcile"]["balances"],
                       "ai": detail["ai"]["reconcile"]["balances"]},
        "scope_counts": detail["scope"]["counts"],
        "revision_differs": detail["revision"]["differs"],
    }
    detail["differences"] = _differences(detail)
    return detail


# ── the page ────────────────────────────────────────────────────────────────────────────

def _gbp(v: Any) -> str:
    return f"£{float(v):,.2f}" if isinstance(v, (int, float)) else "—"


def _signed(v: Any) -> str:
    return (("+" if v > 0 else "−" if v < 0 else "") + f"£{abs(float(v)):,.2f}") \
        if isinstance(v, (int, float)) else "—"


def _pctx(v: Any) -> str:
    return (("+" if v > 0 else "") + f"{float(v):.1f}%") if isinstance(v, (int, float)) else ""


def _frac(v: Any) -> str:
    return f"{float(v) * 100:.2f}%" if isinstance(v, (int, float)) else "—"


_WORDS = {"match": "agrees", "warning": "close", "fail": "differs", "not read": "not read",
          "review": "check", "quantities differ": "quantities differ"}


def _word(status: str) -> str:
    return _WORDS.get(status, status or "")


def _e(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def render_html(detail: Dict[str, Any], title: str = "") -> str:
    h = detail["headline"]
    q = detail["quantity"]
    rv = detail["revision"]
    mrec, arec = detail["manual"]["reconcile"], detail["ai"]["reconcile"]

    def line_rows(rows):
        out = []
        for r in rows:
            if r.get("divisor"):
                fmt = (lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "—")
                delta = f"{r['delta']:+.3f}" if r["delta"] is not None else "—"
            else:
                fmt = _frac if r.get("fraction") else _gbp
                delta = (f"{r['delta'] * 100:+.2f} pts" if r.get("fraction") and r["delta"] is not None
                         else _signed(r["delta"]))
            out.append(
                f"<tr id='line-{_e(r['key'])}'><td>{_e(r['label'])}</td><td class=n>{fmt(r['manual'])}</td>"
                f"<td class=n>{fmt(r['ai'])}</td><td class=n>{delta}</td><td class=n>{_pctx(r.get('pct'))}</td>"
                f"<td><span class='st {_e(r['status']).replace(' ', '-')}'>{_e(_word(r['status']))}</span></td>"
                f"<td class=src>{_e(r.get('manual_cell') or '')}</td>"
                f"<td class=src>{_e(r.get('ai_source') or '')}{(' · ' + _e(r['note'])) if r.get('note') else ''}</td></tr>")
        return "".join(out)

    diffs = "".join(
        f"<li><a href='#{_e(d['anchor'])}'>{_e(d['what'])}</a> "
        f"<span class=n>{_signed(d.get('delta_gbp'))}</span> {_e(_pctx(d.get('pct')))} "
        f"<span class=muted>{_e(d.get('detail') or '')}</span></li>"
        for d in detail["differences"]) or "<li class=muted>No difference above the thresholds.</li>"

    com_cats = "".join(
        f"<tr id='commercial-{_e(c['category'])}'><td>{_e(c['label'])}</td><td class=n>{_gbp(c['manual'])}</td>"
        f"<td class=n>{_gbp(c['ai'])}</td><td class=n>{_signed(c['delta'])}</td>"
        f"<td>{_e(c['presence'])}</td></tr>" for c in detail["commercial"]["categories"]) \
        or "<tr><td colspan=5 class=muted>Neither sheet carries delivery, packaging or installation lines.</td></tr>"
    com_lines = "".join(
        f"<tr><td>{_e(x['side'])}</td><td>{_e(x['label'])}</td><td>{_e(x['description'])}</td>"
        f"<td>{_e(x['where'])}</td><td class=n>{_gbp(x['gbp'])}</td><td class=src>{_e(x.get('cell') or '')}</td>"
        f"<td>{_e(x['note'] or ', '.join(c['description'] for c in (x['counterpart'] or []))[:80])}</td></tr>"
        for x in detail["commercial"]["lines"])

    def part_row(p):
        flags = []
        if p["only_on"]:
            flags.append(f"only on the {p['only_on']} estimate")
        if p["made_bought_differs"]:
            flags.append(f"made or bought differs ({p['manual']['kind']} / {p['ai']['kind']})")
        if p["material_not_charged_on"]:
            flags.append(f"material not charged on the {p['material_not_charged_on']} estimate")
        if p["qty_differs"]:
            flags.append(f"qty per unit {p['manual']['qty']:g} / {p['ai']['qty']:g}")
        for i in p["inputs"]:
            flags.append(f"{i['field']} {i['manual']:g} / {i['ai']:g}")
        return (f"<tr id='part-{_slug(p['code'])}'><td>{_e(p['code'])}</td><td>{_e(p['description'])}</td>"
                f"<td>{_e(p['manual']['kind'] or '—')}</td><td>{_e(p['ai']['kind'] or '—')}</td>"
                f"<td class=n>{_gbp(p['manual']['gbp'])}</td><td class=n>{_gbp(p['ai']['gbp'])}</td>"
                f"<td class=n>{_signed(p['delta'])}</td>"
                f"<td class=src>{_e(', '.join(p['manual']['cells'][:3]))}</td>"
                f"<td class=src>{_e(', '.join(p['ai']['cells'][:3]))}</td><td>{_e('; '.join(flags))}</td></tr>")

    parts = detail["scope"]["parts"]
    flagged = [p for p in parts if p["flagged"]]
    calm = [p for p in parts if not p["flagged"]]
    head_row = ("<tr><th>Part</th><th>Description</th><th>Manual</th><th>AI</th><th>Manual £</th>"
                "<th>AI £</th><th>AI − manual</th><th>Manual cell</th><th>AI cell</th><th>Why it is listed</th></tr>")
    sc = detail["scope"]["counts"]
    calm_html = ("<details><summary>" + ("The part that agrees" if len(calm) == 1
                                         else f"The {len(calm)} parts that agree") + "</summary>"
                 "<div class=wrap><table>" + head_row + "".join(part_row(p) for p in calm)
                 + "</table></div></details>") if calm else ""
    lab = "".join(
        f"<tr id='dept-{_slug(d['department'])}'><td>{_e(d['department'])}</td><td class=n>{_gbp(d['manual'])}</td>"
        f"<td class=n>{_gbp(d['engine'])}</td><td class=n>{_signed(d['delta'])}</td>"
        f"<td class=n>{_gbp(d['manual_setup'])} / {_gbp(d['engine_setup'])}</td>"
        f"<td class=n>{_gbp(d['manual_run'])} / {_gbp(d['engine_run'])}</td></tr>"
        for d in detail["labour"]["rows"])
    problems = [*(f"Manual: {x}" for x in detail["manual"]["problems"]),
                *(f"AI: {x}" for x in detail["ai"]["problems"])]

    def rec(r):
        return (f"material lines {_gbp(r['material_lines'])} against a stated {_gbp(r['material_stated'])}; "
                f"labour lines {_gbp(r['labour_lines'])} against {_gbp(r['labour_stated'])} — "
                + ("adds up" if r["balances"] else "<b>does not add up</b>, so its lines are suspect"))
    st = _e(h["status"]).replace(" ", "-")
    return f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">
<title>{_e(title or 'Parity')} — AI against manual</title>
<style>
:root{{--bg:#fff;--ink:#1a1e1c;--muted:#5b625e;--line:#d5dad7;--ok:#1d7a46;--warn:#9a6200;--bad:#b42318;--chip:#f2f4f3}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111312;--ink:#eceeed;--muted:#a3aaa6;--line:#2c312e;--ok:#5fd08a;--warn:#ffb547;--bad:#ff7a6b;--chip:#1c201e}}}}
body{{font:14px/1.5 "Segoe UI",Arial,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
main{{max-width:1180px;margin:0 auto;padding:20px 16px 60px}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:17px;margin:26px 0 8px}}
table{{border-collapse:collapse;width:100%;margin:6px 0 10px}}td,th{{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-weight:600;font-size:12.5px;color:var(--muted)}}td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.src{{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}}.muted{{color:var(--muted)}}
.st{{padding:1px 8px;border-radius:9px;background:var(--chip);font-size:12px;white-space:nowrap}}
.st.match{{color:var(--ok)}}.st.warning{{color:var(--warn)}}.st.fail,.st.quantities-differ{{color:var(--bad)}}
.big{{font-size:26px;font-weight:700}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}}
.card{{border:1px solid var(--line);border-radius:8px;padding:10px 12px}}.wrap{{overflow-x:auto}}
ul.diffs li{{margin:3px 0}}a{{color:inherit}}details summary{{cursor:pointer;color:var(--muted)}}
</style><main>
<h1>{_e(title or 'Parity')}: AI against manual</h1>
<p class=muted>Differences are AI against manual, signed. The manual estimate is the comparison, not
automatically the right answer. Internal costing only. Thresholds: agrees within {detail['thresholds_pct']['match']:g}%,
close within {detail['thresholds_pct']['warning']:g}%.</p>
<div class=cards>
<div class=card><div class=muted>Total unit cost{(' at ' + format(h['compared_at_qty'], 'g') + ' off') if h.get('compared_at_qty') else ''}</div>
<div class=big>{_gbp(h['ai_unit_cost_gbp'])} <span class=muted style='font-size:14px'>AI</span></div>
<div>{_gbp(h['manual_unit_cost_gbp'])} manual · {_signed(h['gap_gbp'])} {_pctx(h['pct'])}</div>
<div><span class='st {st}'>{_e(_word(h['status']))}</span></div></div>
<div class=card><div class=muted>Sell price{(' at ' + format(h['compared_at_qty'], 'g') + ' off') if h.get('compared_at_qty') else ''}</div><div class=big>{_gbp(h['ai_sell_gbp'])} <span class=muted style='font-size:14px'>AI</span></div>
<div>{_gbp(h['manual_sell_gbp'])} manual</div><div class=muted>compared only with each other</div></div>
<div class=card><div class=muted>Scope</div><div class=big>{sc['parts']} parts</div>
<div>{sc['manual_only']} only manual · {sc['ai_only']} only AI · {sc['made_bought_differs']} made/bought differ · {sc['material_not_charged']} material not charged</div></div>
<div class=card><div class=muted>Quantity and revision</div><div>Manual {_e(format(q['manual'], 'g') if isinstance(q['manual'], (int, float)) else '—')} off · AI {_e(format(q['ai'], 'g') if isinstance(q['ai'], (int, float)) else '—')} off</div>
<div>Revision manual {_e(rv['manual'] or '—')} · AI {_e(rv['ai'] or '—')}{' · <b>differs</b>' if rv['differs'] else ''}</div>
<div class=muted>{_e(q['note'] or rv['note'])}</div></div>
</div>
<h2>The biggest differences</h2><ul class=diffs>{diffs}</ul>
<h2>How each side adds up</h2>
<p>Manual: {rec(mrec)}.<br>AI ({_e(detail['ai'].get('basis') or '')}): {rec(arec)}.</p>
{('<ul>' + ''.join(f'<li class=muted>{_e(x)}</li>' for x in problems) + '</ul>') if problems else ''}
<h2>Cost build-up</h2><div class=wrap><table><tr><th>Line</th><th class=n>Manual</th><th class=n>AI</th><th class=n>AI − manual</th><th class=n>%</th><th></th><th>Manual cell</th><th>AI source</th></tr>{line_rows(detail['cost_build'])}</table></div>
<h2>Selling price</h2><div class=wrap><table><tr><th>Line</th><th class=n>Manual</th><th class=n>AI</th><th class=n>AI − manual</th><th class=n>%</th><th></th><th>Manual cell</th><th>AI source</th></tr>{line_rows(detail['selling'])}</table></div>
<h2>Delivery, packaging and installation</h2><div class=wrap><table><tr><th>Kind</th><th class=n>Manual</th><th class=n>AI</th><th class=n>AI − manual</th><th>On</th></tr>{com_cats}</table>
{('<table><tr><th>Sheet</th><th>Kind</th><th>Line</th><th>Where</th><th class=n>£</th><th>Cell</th><th>Counterpart</th></tr>' + com_lines + '</table>') if com_lines else ''}</div>
<h2>Scope, part by part</h2><p class=muted>{sc['in_both']} parts on both · {sc['manual_only']} only on the manual · {sc['ai_only']} only on the AI ·
{sc['made_bought_differs']} made on one and bought on the other · {sc['qty_differs']} with a different quantity per unit · {sc['material_not_charged']} with material not charged on one side.</p>
<div class=wrap><table>{head_row}{''.join(part_row(p) for p in flagged) or '<tr><td colspan=10 class=muted>Every part agrees.</td></tr>'}</table></div>
{calm_html}
<h2>Labour by department</h2><div class=wrap><table><tr><th>Department</th><th class=n>Manual</th><th class=n>AI</th><th class=n>AI − manual</th><th class=n>Set-up manual / AI</th><th class=n>Run manual / AI</th></tr>{lab}</table></div>
<h2>Sources</h2><p class=src>Manual: {_e(detail['manual']['path'])}<br>AI: {_e(detail['ai']['path'])}</p>
</main></html>"""


def write(detail: Dict[str, Any], out_dir: str | Path, stem: str) -> Tuple[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    j = out / f"{stem}.parity_detail.json"
    h = out / f"{stem}.parity.html"
    j.write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")
    h.write_text(render_html(detail, stem), encoding="utf-8")
    return str(j), str(h)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="The AI estimate against the manual one, line by line.")
    ap.add_argument("--ai", required=True, help="the engine's summary .json")
    ap.add_argument("--manual", required=True, help="the manual estimate workbook")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args(argv)
    detail = compare(a.ai, a.manual)
    j, h = write(detail, a.out_dir, Path(a.ai).stem)
    print(json.dumps({"detail_json": j, "detail_html": h, "headline": detail["headline"]}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
