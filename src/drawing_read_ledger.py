"""What the drawing's own text stated reaches the charged cells, or the release is held
(SCRUM-194, requirement 2).

read_charge_contract (D-596) holds an LLM read to the calculated workbook: every item the model
returned ends charged, covered, excluded or unresolved. The deterministic read had no such
ledger. 0358141's 09:32 record carried a read_charge_result that said "no LLM read was taken,
so this contract checked nothing", a section contract with no requirement (the pack prints no
cut-list table) and a material contract that verified nothing; the facts the reader extracted
and linked (D-758 to D-762) were held to no row. The reviewer, 9 Nov 2026: every
costing-relevant finding must be used, covered elsewhere, superseded or excluded with a reason,
or flagged unresolved, with the row identified, and "extracted and linked" at the scan stage is
not "charged".

THE DRAWING LEDGER (captured once the deterministic build is done, before costing,
`summary["drawing_ledger"]`). Every fact the drawing's own text gave a made part, in the same
item shape as the read ledger so the same audit dispositions it: the part (D1, D2 ...), its
quantity, its material, its size (a blank, or a section with its length and pieces), each
operation the sheet states (said_by names the reading: a note, a title-block field, a
callout), and each feature. Each item carries the page it was read from and the words. Only
facts READ FROM THE DRAWING go in: an operation the engine inferred is the engine's allowance,
listed apart by the audit, never a drawing fact.

THE FINAL STATE is read_charge_contract.audit over this ledger after Excel
(`summary["drawing_charge_result"]`), and invariants hold the release on an unresolved item
exactly as for the read ledger.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "drawing_ledger.v1"
SAID_BY = "drawing_deterministic"
# A value set by the drawing's own reading is the drawing's, not a correction (what the audit
# treats as "the read's own rank"; see read_charge_contract._READ_SOURCES).
READ_SOURCES = {"", "drawing_deterministic", "drawing_notes", "title_block", "title_block_region",
                "pdf_text", "detail_sheet_overall", "tube_callout", "tube_callouts"}
# Operation sources that are a reading of the sheet or the pack's own geometry, not an
# inference. "drawing_deterministic" is NOT one: the estimator stamps a saw with its section's
# source, so a saw inferred from a stated tube carries the tube's source and no words of its
# own. An operation with no quoted words and no reading source is the engine's allowance.
_STATED_OP_SOURCES = {"drawing_notes", "title_block", "tube_callout", "dxf", "dxf_geometry",
                      "model", "solidworks"}


def _pn(v: Any) -> str:
    return " ".join(str(v or "").split()).strip().upper()


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _page_of(part: Mapping[str, Any], *keys: str) -> Any:
    for k in keys:
        v = part.get(k)
        if isinstance(v, Mapping) and v.get("page"):
            return v["page"]
        if isinstance(v, list) and v and isinstance(v[0], Mapping) and v[0].get("page"):
            return v[0]["page"]
    pages = [p for p in (part.get("pages") or []) if p != part.get("bound_to_parts_list_page")]
    return pages[0] if len(pages) == 1 else (pages or None)


# A finish the sheet states is work the sheet asks for (JG, 9 Nov 2026: if it states on the
# drawing, it is needed). The family names what the audit looks for: a coat in the coating rows,
# a polish or a brushed grain in the polishing or brushing rows, a plate in the plating line.
_FINISH_ITEM = {"powder": "coat", "wet_spray": "coat", "polish": "polish", "brushed": "brushed",
                "plate": "plate", "anodise": "anodise"}
_MODEL_SOURCES = ("llm", "vision", "grok", "model")


def _stated_finish(part: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """The finish this part's sheet states, as a ledger statement, or None: a bare finish (RAW)
    states no work, and a finish a model read is not the drawing's own text."""
    src = str(part.get("finish_source") or "").lower()
    if any(m in src for m in _MODEL_SOURCES):
        return None
    try:
        import finish_rules as fr
        text = fr.stated_finish(part)
        fams = fr.finish_families(text) if text else set()
    except Exception:                                                # noqa: BLE001
        return None
    for fam, what in _FINISH_ITEM.items():
        if fam in fams:
            # THE WORD THAT STATES IT, NOT THE SCRAPE AROUND IT: a title-block finish field
            # often carries its neighbours' text; the ledger shows the stating word and keeps
            # the whole field as the words it was read from.
            said = text
            for tok in fr.FINISH_FAMILIES.get(fam) or ():
                m = re.search(r"\S*" + re.escape(tok).replace(r"\ ", r"\s+") + r"\S*", text)
                if m:
                    said = m.group(0)
                    break
            return {"item": what, "text": text, "as_read": said}
    return None


def capture(summary: Mapping[str, Any], parts: Optional[Iterable[Mapping[str, Any]]] = None
            ) -> Dict[str, Any]:
    """The drawing's stated facts per made part, each with its page and words. Pure."""
    recs = list(parts) if parts is not None else list(
        ((summary.get("manufacturing_writeup") or {}).get("parts") or []))
    items: List[Dict[str, Any]] = []

    def add(**item: Any) -> None:
        item.setdefault("said_by", SAID_BY)
        items.append(item)

    n = 0
    for part in recs:
        if not isinstance(part, Mapping):
            continue
        pn = _pn(part.get("part_number"))
        if not pn or part.get("is_bought_in") or "bought_in" in (part.get("page_roles") or []):
            continue
        try:
            from bought_in_policy import is_bought_in as _bought
            if _bought(part):
                continue                    # a purchase; the drawing states no work on it
        except Exception:                                            # noqa: BLE001
            pass
        own_pages = [p for p in (part.get("pages") or []) if p != part.get("bound_to_parts_list_page")]
        if not own_pages and not part.get("section_stock") and not part.get("materials"):
            continue                        # nothing of its own was read: nothing to hold
        n += 1
        rid = f"D{n}"
        name = str(part.get("description") or pn)
        page = _page_of(part, "title_block_identity")
        add(id=rid, kind="part", work=True, label=name, record=pn, link="part_number",
            page=page, as_read={"name": name, "part_number": pn, "pages": own_pages})
        if _num(part.get("quantity")) is not None:
            add(id=f"{rid}.quantity", kind="quantity", work=False, label=f"{name}: quantity",
                record=pn, of=rid, page=page, as_read=_num(part.get("quantity")))
        mats = [m for m in (part.get("materials") or []) if m]
        if mats:
            tbm = part.get("title_block_material") if isinstance(part.get("title_block_material"), Mapping) else {}
            add(id=f"{rid}.material", kind="material", work=False, label=f"{name}: material",
                record=pn, of=rid, page=tbm.get("page") or page, as_read=mats[0],
                words=tbm.get("printed") or part.get("material_text_as_printed"))
        ss = part.get("section_stock") if isinstance(part.get("section_stock"), Mapping) else {}
        if ss.get("a"):
            add(id=f"{rid}.section", kind="section", work=False, label=f"{name}: section",
                record=pn, of=rid, page=page,
                as_read={"a": ss.get("a"), "b": ss.get("b"), "t": ss.get("t"),
                         "length_mm": ss.get("length_mm"), "cut_lengths_mm": ss.get("cut_lengths_mm"),
                         "length_source": ss.get("length_source")},
                words=ss.get("length_printed") or ss.get("source_text"))
        else:
            size = {"length": _num(part.get("blank_length_mm")), "width": _num(part.get("blank_width_mm")),
                    "thickness": _num(part.get("normalized_thickness_mm"))}
            if any(v for v in size.values()):
                add(id=f"{rid}.size", kind="size", work=False, label=f"{name}: size", record=pn,
                    of=rid, page=part.get("blank_page") or page,
                    as_read={k: v for k, v in size.items() if v},
                    words=part.get("blank_printed") or part.get("material_text_as_printed"),
                    said_by=str(part.get("blank_length_mm_source") or SAID_BY))
        fin = _stated_finish(part)
        if fin:
            add(id=f"{rid}.finish", kind="stated", work=True, item=fin["item"], label=f"{name}: finish",
                record=pn, of=rid, page=page, as_read=fin["as_read"], text=fin["text"],
                words=part.get("finish_text_as_printed") or fin["text"],
                said_by=str(part.get("finish_source") or SAID_BY))
        for k, feat in enumerate(part.get("stated_features") or [], start=1):
            if not isinstance(feat, Mapping):
                continue
            fk = str(feat.get("kind") or "")
            what = ("hole" if fk == "hole" else f"thread {feat.get('thread')}" if fk == "thread"
                    else "countersink" if fk == "countersink" else fk)
            add(id=f"{rid}.feature.{k}", kind="feature", work=True, item=what,
                label=f"{name}: {what}" + (f" x{feat.get('count')}" if feat.get("count") else ""),
                record=pn, of=rid, page=feat.get("page") or page,
                as_read={x: feat.get(x) for x in ("diameter_mm", "count", "thread", "angle_deg", "purpose")
                         if feat.get(x) is not None},
                words=feat.get("words"), said_by=str(feat.get("source") or "drawing_notes"))
        srcs = part.get("operation_sources") if isinstance(part.get("operation_sources"), Mapping) else {}
        ev = part.get("operation_evidence") if isinstance(part.get("operation_evidence"), Mapping) else {}
        for op in part.get("textual_operations") or []:
            o = str(op).strip().lower()
            if not o or o == "handling":
                continue
            src = str(srcs.get(o) or "")
            if not ev.get(o) and src not in _STATED_OP_SOURCES:
                continue                    # unquoted and not a reading: the engine's allowance
            add(id=f"{rid}.op.{o}", kind="operation", work=True, item=o, label=f"{name}: {o}",
                record=pn, of=rid, page=page, as_read=o, words=ev.get(o), said_by=src or SAID_BY)
    return {"schema": SCHEMA, "said_by": SAID_BY, "read_sources": sorted(READ_SOURCES),
            "items": items, "parts_read": n}
