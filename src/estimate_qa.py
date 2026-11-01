#!/usr/bin/env python3
"""THE QUESTION SERVICE: one finished estimate, one saved record, asked read-only.

    echo {"question": "...", "record_path": "..."} | python src\\estimate_qa.py

D-610 built it for the e-mail's walkthrough page; D-615 put the estimating app's "Ask about a
saved estimate" box on it; D-616 made it the ONE service both ask, so the same saved estimate
gives the same answer through either. It prints one line of JSON and changes nothing: no run,
no file written, no price worked out.

WHICH RECORD. Exactly one, chosen by the caller and named in every reply:
  `record`       the record itself, as the app's box already chose and read it;
  `record_path`  one saved record file;
  `records`      the run's own files (the walkthrough page): the single *_record.json among
                 them, else the single JSON that carries an estimate. Two candidates, or none,
                 is "record unavailable", never a guess.
`record_name` and `run_id`, where the caller has them, come back in every reply, answered or
not. A record that cannot be had, or holds nothing to answer from, stops here with "Record
unavailable": the model is never asked with empty evidence.

RECORDED FIGURES COME FROM THE RECORD, NOT THE MODEL. Every reply carries `recorded`: the unit
cost and its cell, the price at each quantity, any part the question names with its charged
figure, and the release status, read straight from the record. The model explains them; it is
told never to work out a price, and any money in its answer that is not a figure in the record
is refused and not shown (`refused_figures`).

WHAT THE MODEL SAW, SAID. The largest lines go, plus every part and line the question names;
`coverage` counts shown against held for each list, and `coverage_note` says plainly when the
answer rests on part of the record. The model is told the same and to say so.

THE MODEL. The configured Grok text model (xai_models, grok-4.7 by default), through
web_ai_price_lookup._call_xai_llm; `model` names it. SDI_OFFLINE stops it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

PARTS_MAX = 40
LINES_MAX = 25
LIST_MAX = 30
NAMED_MAX = 20
_MAX_CONTEXT_CHARS = 18000
_MAX_RECORD_BYTES = 30_000_000
_MONEY_IN_TEXT = re.compile(r"£\s*(-?[0-9][0-9,]*(?:\.[0-9]+)?)")
_PRICE_WORDS = ("price", "cost", "total", "how much", "unit", "quote", "charge", "£",
                "come out", "came out", "quantity", "off", "break")
_RELEASE_WORDS = ("release", "warning", "flag", "outstanding", "confirm", "hold", "held",
                  "risk", "missing", "open", "provisional", "draft", "check", "issue")


def _money(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _gbp(v: Any) -> str:
    m = _money(v)
    return f"£{m:,.2f}" if m is not None else "not recorded"


def _dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _carries_an_estimate(doc: Any) -> bool:
    return isinstance(doc, dict) and bool(doc.get("final_estimate") or doc.get("costed_job")
                                          or doc.get("quantity_sweep"))


# ── which record ────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        if path.stat().st_size > _MAX_RECORD_BYTES:
            return {}, f"{path.name} is too large to read here"
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"{path.name} could not be read ({type(exc).__name__})"
    return (doc, "") if isinstance(doc, dict) else ({}, f"{path.name} is not a saved record")


def pick_record(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    """(record, record name, why unavailable). Exactly one record, or none and the reason."""
    name = str(payload.get("record_name") or "")
    if isinstance(payload.get("record"), dict):
        return payload["record"], name or "the selected record", ""
    if payload.get("record_path"):
        path = Path(str(payload["record_path"]))
        doc, why = _read(path)
        return doc, path.name, why
    paths = [Path(str(p)) for p in payload.get("records") or [] if str(p).strip()]
    pinned = [p for p in paths if p.name.lower().endswith("_record.json")]
    if len(pinned) > 1:
        return {}, "", (f"{len(pinned)} saved records belong to this run, so it is not clear "
                        f"which to answer from")
    if pinned:
        doc, why = _read(pinned[0])
        return doc, pinned[0].name, why
    found = []
    for p in paths:
        doc, _ = _read(p)
        if _carries_an_estimate(doc):
            found.append((doc, p.name))
    if len(found) == 1:
        return found[0][0], found[0][1], ""
    if found:
        return {}, "", f"{len(found)} saved files carry an estimate, so it is not clear which"
    return {}, "", "no saved estimate record was found for this run"


# ── what goes to the model, and what is left out ───────────────────────────────────────

def _named(question: str, *texts: Any) -> bool:
    """Does the question name this part or line? Part numbers compared without punctuation;
    a description by its longer words."""
    q = question.lower()
    q_bare = re.sub(r"[^a-z0-9]", "", q)
    for text in texts:
        t = str(text or "").strip().lower()
        if not t:
            continue
        bare = re.sub(r"[^a-z0-9]", "", t)
        if len(bare) >= 5 and any(ch.isdigit() for ch in bare) and bare in q_bare:
            return True
        words = [w for w in re.findall(r"[a-z]{4,}", t)]
        if words and len(words) <= 4 and all(w in q for w in words):
            return True
    return False


def _choose(rows: List[Dict[str, Any]], question: str, keys: Iterable[str], value: str,
            limit: int) -> Tuple[List[Dict[str, Any]], int, int]:
    """(rows to send, how many the question named, how many the record holds): every row the
    question names, then the largest by `value`, up to `limit` beyond the named ones."""
    keys = list(keys)
    named = [r for r in rows if _named(question, *(r.get(k) for k in keys))][:NAMED_MAX]
    rest = sorted((r for r in rows if r not in named),
                  key=lambda r: -(_money(r.get(value)) or 0))[:limit]
    return named + rest, len(named), len(rows)


def evidence(record: Dict[str, Any], question: str,
             quantity_prices: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What the answer may use, with a count of what was held and what was sent."""
    final = _dict(record.get("final_estimate"))
    totals = _dict(final.get("totals"))
    costed = _dict(record.get("costed_job"))
    run = _dict(costed.get("run"))
    release = _dict(costed.get("release")) or _dict(record.get("release_decision"))
    lines = [l for l in costed.get("lines") or [] if isinstance(l, dict)]
    labour = [r for r in final.get("labour_rows") or [] if isinstance(r, dict)]
    material = [r for r in final.get("material_rows") or [] if isinstance(r, dict)]
    decisions = [d for d in costed.get("decisions_required") or [] if isinstance(d, dict)]
    flags = [str(f) for f in record.get("review_flags") or []]
    reasons = [str(r) for r in release.get("reasons") or []]

    parts, parts_named, parts_held = _choose(
        lines, question, ("part_number", "description"), "charged_ext_gbp", PARTS_MAX)
    lab, lab_named, lab_held = _choose(labour, question, ("operation", "part_number"),
                                       "total_value_gbp", LINES_MAX)
    mat, mat_named, mat_held = _choose(material, question, ("description", "part_number"),
                                       "total_value_gbp", LINES_MAX)
    sweep = [r for r in (_dict(record.get("quantity_sweep")).get("rows") or [])
             if isinstance(r, dict)]
    at_each = [{"quantity": p.get("quantity"), "unit_gbp": _money(p.get("unit_gbp"))}
               for p in quantity_prices or [] if isinstance(p, dict)] or [
        {"quantity": r.get("quantity"), "unit_gbp": _money(r.get("unit"))} for r in sweep]
    unit = _money(totals.get("unit_gbp"))
    if unit is None:
        unit = _money(run.get("unit_gbp"))

    known = {
        "drawing": record.get("drawing_number") or record.get("declared_product"),
        "customer": record.get("customer") or record.get("client"),
        "order_quantity": record.get("requested_order_quantity") or run.get("order_qty"),
        "unit_cost_gbp": unit,
        "unit_cell": totals.get("unit_cell") or "",
        "material_gbp": _money(totals.get("material_gbp", run.get("material_gbp"))),
        "labour_gbp": _money(totals.get("labour_gbp", run.get("labour_gbp"))),
        "other_gbp": _money(totals.get("other_gbp")),
        "price_at_each_quantity": [p for p in at_each if p["unit_gbp"] is not None],
        "release": {"status": release.get("status") or "not recorded",
                    "to_confirm": release.get("to_confirm"),
                    "outstanding": release.get("outstanding"),
                    "prices_outstanding": release.get("prices_outstanding"),
                    "decisions_open": release.get("decisions_open"),
                    "reasons": reasons[:LIST_MAX]},
        "outstanding_items": [{"kind": d.get("kind"), "part": d.get("part"),
                               "what": d.get("text") or d.get("issue") or d.get("why")
                               or d.get("description") or ""}
                              for d in decisions[:LIST_MAX]],
        "review_flags": flags[:LIST_MAX],
        "parts": [{"part": str(l.get("part_number") or ""),
                   "description": str(l.get("description") or ""),
                   "per_unit": l.get("qty_per_unit"),
                   "material": str(l.get("material_label") or ""),
                   "kind": str(l.get("kind") or ""),     # bought_in, commercial, sheet_row...
                   "block": str(l.get("block") or ""),
                   "charged_unit_gbp": _money(l.get("charged_unit_gbp")),
                   "charged_gbp": _money(l.get("charged_ext_gbp")),
                   "charged_cell": l.get("charged_cell") or ""} for l in parts],
        "labour_lines": [{"line": str(r.get("operation") or r.get("description") or ""),
                          "part": str(r.get("part_number") or ""),
                          "gbp": _money(r.get("total_value_gbp"))} for r in lab],
        "material_lines": [{"line": str(r.get("description") or r.get("operation") or ""),
                            "part": str(r.get("part_number") or ""),
                            "gbp": _money(r.get("total_value_gbp"))} for r in mat],
    }
    coverage = {
        "parts": [len(parts), parts_held], "labour_lines": [len(lab), lab_held],
        "material_lines": [len(mat), mat_held],
        "outstanding_items": [min(len(decisions), LIST_MAX), len(decisions)],
        "review_flags": [min(len(flags), LIST_MAX), len(flags)],
        "release_reasons": [min(len(reasons), LIST_MAX), len(reasons)],
    }
    sources = [s for s, held in (
        ("final_estimate.totals", bool(totals)), ("costed_job.run", bool(run)),
        ("costed_job.lines", bool(lines)), ("final_estimate.labour_rows", bool(labour)),
        ("final_estimate.material_rows", bool(material)),
        ("costed_job.release", bool(_dict(costed.get("release")))),
        ("release_decision", not _dict(costed.get("release"))
         and bool(_dict(record.get("release_decision")))),
        ("costed_job.decisions_required", bool(decisions)), ("review_flags", bool(flags)),
        ("quantity_sweep", bool(sweep)), ("quantity_prices", bool(quantity_prices)))
               if held]
    return {"known": known, "coverage": coverage, "sources": sources,
            "named_parts": parts[:parts_named], "usable": bool(
                unit is not None or lines or labour or material or release or decisions)}


def coverage_note(coverage: Dict[str, List[int]]) -> str:
    """Plain words for what the model did not see, or "" when it saw everything."""
    words = {"parts": "parts", "labour_lines": "labour lines", "material_lines":
             "material lines", "outstanding_items": "outstanding items",
             "review_flags": "review flags", "release_reasons": "release reasons"}
    short = [f"{shown} of {held} {words[k]}" for k, (shown, held) in coverage.items()
             if held > shown]
    if not short:
        return ""
    return ("Answered from part of the record: " + ", ".join(short) + " (any the question "
            "names, then the largest). The workbook and the report hold the rest.")


# ── figures straight from the record ───────────────────────────────────────────────────

def recorded(ev: Dict[str, Any], question: str) -> List[str]:
    """The record's own figures for this question, read directly: never the model's."""
    k = ev["known"]
    q = question.lower()
    out = [f"Unit cost {_gbp(k['unit_cost_gbp'])} ex VAT at {k['order_quantity'] or '?'} off"
           + (f", workbook cell {k['unit_cell']}" if k.get("unit_cell") else "") + "."
           if k["unit_cost_gbp"] is not None else "Unit cost: not recorded in this record."]
    if len(k["price_at_each_quantity"]) > 1 and any(w in q for w in _PRICE_WORDS):
        out.append("At each quantity: " + "; ".join(
            f"{p['quantity']} off {_gbp(p['unit_gbp'])}" for p in k["price_at_each_quantity"])
            + ".")
    for p in ev["named_parts"]:
        out.append(f"{p.get('part_number') or 'Unnumbered part'}"
                   + (f" {p.get('description')}" if p.get("description") else "")
                   + (f" [{p.get('kind')}]" if p.get("kind") else "")
                   + f": {p.get('qty_per_unit', '?')} per unit, charged "
                   + f"{_gbp(p.get('charged_ext_gbp'))} per finished unit"
                   + (f" ({p.get('charged_cell')})" if p.get("charged_cell") else "") + ".")
    if any(w in q for w in _RELEASE_WORDS):
        r = k["release"]
        out.append(f"Release: {r['status']}"
                   + (f"; {r['to_confirm']} to confirm" if r.get("to_confirm") is not None
                      else "")
                   + (f" ({r['prices_outstanding']} prices outstanding, {r['decisions_open']} "
                      f"decisions open)" if r.get("prices_outstanding") is not None else "")
                   + ".")
    return out


def allowed_money(ev: Dict[str, Any], *texts: str) -> Set[float]:
    """Every money figure the record holds, and those already written from it."""
    k = ev["known"]
    vals: Set[float] = set()

    def add(v: Any) -> None:
        m = _money(v)
        if m is not None:
            vals.add(m)
    for key in ("unit_cost_gbp", "material_gbp", "labour_gbp", "other_gbp"):
        add(k.get(key))
    for p in k["price_at_each_quantity"]:
        add(p["unit_gbp"])
        if _money(p.get("quantity")) and p["unit_gbp"] is not None:
            add(p["unit_gbp"] * _money(p["quantity"]))
    for group in ("parts", "labour_lines", "material_lines"):
        for row in k[group]:
            add(row.get("charged_gbp", row.get("gbp")))
            add(row.get("charged_unit_gbp"))
    for text in texts:
        for m in _MONEY_IN_TEXT.findall(text or ""):
            add(m.replace(",", ""))
    return vals


def refused_figures(answer: str, allowed: Set[float]) -> List[str]:
    """Money in the model's answer that is not a figure in the record."""
    out = []
    for raw in _MONEY_IN_TEXT.findall(answer or ""):
        value = _money(raw.replace(",", ""))
        if value is None:
            continue
        whole = "." not in raw
        if any(abs(value - a) < 0.005 or (whole and abs(value - a) < 0.5) for a in allowed):
            continue
        out.append(f"£{raw}")
    return out


# ── the question ────────────────────────────────────────────────────────────────────────

def prompt(question: str, known: Dict[str, Any], commentary: str, record_answer: str = "",
           note: str = "") -> str:
    context = json.dumps(known, default=str)[:_MAX_CONTEXT_CHARS]
    lookup = (f"RECORD LOOKUP (a rule-based reading of the same record, exact): "
              f"{record_answer[:2000]}\n\n" if record_answer.strip() else "")
    partial = (f"EVIDENCE: {note} If the question needs what was left out, say the answer "
               f"rests on part of the record.\n\n" if note else
               "EVIDENCE: every line of these lists is included.\n\n")
    return (
        "You answer an SDI estimator's question about ONE finished internal cost estimate.\n"
        "Rules: answer only from the ESTIMATE FACTS and WALKTHROUGH below. If they do not say, "
        "say so plainly and name where to look (the workbook's Estimate sheet or the job "
        "report). Never invent or recalculate a price: quote money exactly as recorded, to "
        "the penny, and only figures that appear below. Explain the figures; do not replace "
        "them. Keep it short: a few sentences, plain English, no markdown. This estimate is "
        "internal and may be provisional; never describe it as a customer quotation.\n\n"
        f"ESTIMATE FACTS (JSON): {context}\n\n"
        f"{partial}"
        f"WALKTHROUGH: {commentary[:4000]}\n\n"
        f"{lookup}"
        f"QUESTION: {question}\n\n"
        'Reply as JSON only: {"answer": "..."}')


def _model_name() -> str:
    try:
        import xai_models
        return xai_models.text_model()
    except Exception:                                                # noqa: BLE001
        return ""


def answer(payload: Dict[str, Any], ask: Any = None) -> Dict[str, Any]:
    """One reply for one question about one saved record. `ask` is for the tests."""
    question = str(payload.get("question") or "").strip()[:1000]
    base: Dict[str, Any] = {"run_id": str(payload.get("run_id") or ""),
                            "record_name": str(payload.get("record_name") or ""),
                            "recorded": [], "sources": [], "coverage": {},
                            "coverage_note": "", "model": "", "refused_figures": []}
    if not question:
        return dict(base, status="unavailable",
                    answer="Type a question about the estimate first.")
    record, name, why = pick_record(payload)
    base["record_name"] = name or base["record_name"]
    if not record:
        return dict(base, status="unavailable", answer=f"Record unavailable: {why}.")
    ev = evidence(record, question, list(payload.get("quantity_prices") or []))
    if not ev["usable"]:
        return dict(base, status="unavailable",
                    answer="Record unavailable: the saved record holds no totals, lines or "
                           "release status to answer from.")
    note = coverage_note(ev["coverage"])
    base.update(recorded=recorded(ev, question), sources=ev["sources"],
                coverage=ev["coverage"], coverage_note=note)
    commentary = str(payload.get("commentary") or "")
    record_answer = str(payload.get("record_answer") or "")
    if ask is None:
        from web_ai_price_lookup import _call_xai_llm as ask
    reply = ask(prompt(question, ev["known"], commentary, record_answer, note),
                max_completion_tokens=2500, temperature=0.0)
    text = str((reply or {}).get("answer") or "").strip() if isinstance(reply, dict) else ""
    if not text:
        return dict(base, status="unavailable",
                    answer="No answer came back from the model (it may be offline, or the key "
                           "is not set on this machine). The recorded figures above are read "
                           "from the record; the workbook and report hold every figure.")
    model = _model_name()
    refused = refused_figures(text, allowed_money(ev, commentary, record_answer))
    if refused:
        return dict(base, status="answered", model=model, refused_figures=refused,
                    answer=(f"The model's explanation quoted {', '.join(refused)}, which "
                            f"{'is' if len(refused) == 1 else 'are'} not in this record, so "
                            f"it is not shown. The recorded figures above are the record's "
                            f"own. Ask again more narrowly."))
    return dict(base, status="answered", answer=text, model=model)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    try:
        import config  # noqa: F401  — loads .env, so XAI_API_KEY is there
    except Exception:                                                # noqa: BLE001
        pass
    print(json.dumps(answer(payload if isinstance(payload, dict) else {}), default=str),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
