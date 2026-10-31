#!/usr/bin/env python3
"""Questions about one finished estimate, answered from its own record (D-610).

    echo {"question": "...", "records": [...], "commentary": "..."} | python src\\estimate_qa.py

The walkthrough page's question box. The service hands this the question, the run's saved
records and the walkthrough's words; this prints one line of JSON: {"status", "answer"}.

ANSWERED FROM THE ESTIMATE, NOTHING ELSE. The model is given the figures the run itself wrote,
the unit cost at each quantity, the labour and material lines, what is still to confirm and
the walkthrough's words, and told to answer from them alone: to say where the record does not
say, never to work out a new price, and to point at the workbook or report for the detail.

THE SAME MODEL THE ENGINE ALREADY USES. Grok, through web_ai_price_lookup._call_xai_llm, the
call the price lookups and reads already make; no new key and no new provider. The figures go
where the drawings already go. SDI_OFFLINE stops it, as it stops every paid call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

_MAX_LINES = 25
_MAX_CONTEXT_CHARS = 14000


def _money(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _load(paths: List[str]) -> Dict[str, Any]:
    """The run's own record: the first saved JSON that carries an estimate."""
    for p in paths or []:
        try:
            doc = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and (doc.get("final_estimate") or doc.get("quantity_sweep")
                                      or doc.get("manufacturing_writeup")):
            return doc
    return {}


def facts(record: Dict[str, Any], quantity_prices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The figures the answer may use, compact enough to send."""
    final = record.get("final_estimate") if isinstance(record.get("final_estimate"), dict) else {}
    totals = final.get("totals") if isinstance(final.get("totals"), dict) else {}

    def _rows(key: str, label: str) -> List[Dict[str, Any]]:
        rows = [r for r in (final.get(key) or []) if isinstance(r, dict)]
        rows.sort(key=lambda r: -(_money(r.get("total_value_gbp")) or 0))
        return [{"line": str(r.get(label) or r.get("description") or r.get("operation") or ""),
                 "part": str(r.get("part_number") or r.get("part") or ""),
                 "gbp": _money(r.get("total_value_gbp"))} for r in rows[:_MAX_LINES]]

    flags = [str(f) for f in (record.get("review_flags") or [])][:15]
    return {
        "drawing": record.get("drawing_number") or record.get("declared_product"),
        "customer": record.get("customer") or record.get("client"),
        "order_quantity": record.get("requested_order_quantity"),
        "unit_cost_gbp": _money(totals.get("unit_gbp")),
        "material_gbp": _money(totals.get("material_gbp")),
        "labour_gbp": _money(totals.get("labour_gbp")),
        "price_at_each_quantity": quantity_prices or [
            {"quantity": r.get("quantity"), "unit_gbp": _money(r.get("unit"))}
            for r in ((record.get("quantity_sweep") or {}).get("rows") or [])
            if isinstance(r, dict)],
        "labour_lines": _rows("labour_rows", "operation"),
        "material_lines": _rows("material_rows", "description"),
        "review_flags": flags,
        "release": (record.get("release_decision") or {}).get("status")
        if isinstance(record.get("release_decision"), dict) else None,
    }


def prompt(question: str, known: Dict[str, Any], commentary: str) -> str:
    context = json.dumps(known, default=str)[:_MAX_CONTEXT_CHARS]
    return (
        "You answer an SDI estimator's question about ONE finished internal cost estimate.\n"
        "Rules: answer only from the ESTIMATE FACTS and WALKTHROUGH below. If they do not say, "
        "say so plainly and name where to look (the workbook's Estimate sheet or the job "
        "report). Never invent or recalculate a price. Quote money in pounds as given. Keep "
        "it short: a few sentences, plain English, no markdown. This estimate is internal "
        "and may be provisional; never describe it as a customer quotation.\n\n"
        f"ESTIMATE FACTS (JSON): {context}\n\n"
        f"WALKTHROUGH: {commentary[:4000]}\n\n"
        f"QUESTION: {question}\n\n"
        'Reply as JSON only: {"answer": "..."}')


def answer(payload: Dict[str, Any], ask: Any = None) -> Dict[str, str]:
    """{"status": "answered" | "unavailable", "answer": "..."}. `ask` is for the tests."""
    question = str(payload.get("question") or "").strip()
    if not question:
        return {"status": "unavailable", "answer": "Type a question about the estimate first."}
    record = _load(list(payload.get("records") or []))
    known = facts(record, list(payload.get("quantity_prices") or []))
    if ask is None:
        from web_ai_price_lookup import _call_xai_llm as ask
    reply = ask(prompt(question, known, str(payload.get("commentary") or "")),
                max_completion_tokens=2500, temperature=0.0)
    text = str((reply or {}).get("answer") or "").strip() if isinstance(reply, dict) else ""
    if not text:
        return {"status": "unavailable",
                "answer": "No answer came back from the model (it may be offline, or the key "
                          "is not set on this machine). The workbook and report hold every "
                          "figure."}
    return {"status": "answered", "answer": text}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    try:
        import config  # noqa: F401  — loads .env, so XAI_API_KEY is there
    except Exception:                                                # noqa: BLE001
        pass
    print(json.dumps(answer(payload if isinstance(payload, dict) else {})), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
