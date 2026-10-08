"""A run that produced nothing to cost says so ONCE, and every deliverable reads it (D-409).

12675-01, 8 Oct 2026, the first run after D-406 closed both doors: no part was minted and no
labour row was written — and the book was not empty. Packaging and delivery were minted for a
product that did not exist (£23.00), the customer's commercial terms ran over them (£25.46 a
unit), the sheet's labour total of exactly zero was read back as missing, so the unit cost went
out as "PENDING — NOT TRACEABLE TO A WORKBOOK CELL", the report's headline read "Not for release
— 3 to settle" over two decisions about packing nothing, and the one sentence that explained the
run — the design-intent stop — appeared on no page and no sheet.

Every surface had been told about the stop by a review flag none of them read, and each carried
on as if the parts list had simply come back short. The stop is now a STRUCTURED FACT on the
record, written where the scan decides it and asked by everything downstream: the commercial
lines (nothing to pack), the quote (no price), the workbook banner, the report's headline and
Decisions table, the explanation tab. One producer, one sentence, every surface.

The stop is recorded only where nothing can add a part afterwards, so "this run produced nothing
to cost" is a fact about the finished record and not a stage that has not run yet.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

KEY = "run_stop"

# What stopped the run, in the reader's words. The kind is the engine's own vocabulary (it is
# what file_scan records); the sentence is for the person. A kind this table does not know is
# still recorded and still empties the book — it is printed de-underscored, never dropped.
KINDS: Dict[str, str] = {
    "design_intent_pack_on_engine_run":
        "the pack is design-intent sheets, with no parts list and no part drawings, so the "
        "drawing readers had nothing to cost",
    "image_render_pack_on_engine_run":
        "the pack is image renders, which the drawing readers cannot measure",
    "concept_read_refused":
        "the pack has measurable geometry that produced no parts, so the concept read was "
        "refused rather than guess from pictures",
}


def record(summary: Dict[str, Any], kind: str, reason: str, *, next_step: str = "",
           **detail: Any) -> Dict[str, Any]:
    """Write the stop onto the record. `reason` is the full sentence the scan already says in
    its review flag; `next_step` is what answers the pack; `detail` carries the evidence (the
    pages, the refusal) for the surfaces that have room for it."""
    stop: Dict[str, Any] = {
        "kind": str(kind or "").strip(),
        "short": KINDS.get(str(kind or "").strip(),
                           str(kind or "").strip().replace("_", " ") or "the run stopped"),
        "reason": str(reason or "").strip(),
        "next_step": str(next_step or "").strip(),
    }
    for k, v in detail.items():
        if v not in (None, "", [], {}):
            stop[k] = v
    summary[KEY] = stop
    return stop


def nothing_to_cost(summary: Any) -> Optional[Dict[str, Any]]:
    """The recorded stop, or None. Accepts a run summary or a costed record carrying one."""
    if not isinstance(summary, Mapping):
        return None
    stop = summary.get(KEY)
    if isinstance(stop, Mapping) and (stop.get("reason") or stop.get("kind")):
        return dict(stop)
    return None


HEADLINE = "NO PRICE — NOTHING TO COST"


def sentence(stop: Mapping[str, Any]) -> str:
    """One sentence for a tile, a banner or a bullet: what stopped the run, then what answers
    it. The same words on every surface, so the sheet and the report cannot disagree about
    why the book is empty."""
    short = str(stop.get("short") or stop.get("kind") or "the run stopped").strip().rstrip(".")
    nxt = str(stop.get("next_step") or "").strip()
    return f"No price — nothing to cost: {short}." + (f" {nxt}" if nxt else "")


def banner(stop: Mapping[str, Any]) -> str:
    """The cell beside Unit Cost and Sell Price. Upper-case lead so it reads as the status it
    is, and never "PROVISIONAL —": that word promises a figure somebody can finish."""
    return "NO PRICE — " + sentence(stop)[len("No price — "):]
