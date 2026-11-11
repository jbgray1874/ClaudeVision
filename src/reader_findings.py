"""What the deterministic reader found on each page, kept BEFORE anything merges, filters or
binds it (SCRUM-194, requirement 2; the reviewer, 9 Nov 2026).

A ledger made from the built part records can only hold what survived the build: a dimension
the reader read and the build dropped is gone before the ledger looks. So the reader's own
findings are captured here, page by page, straight off the page text, with the page, the value,
its units, the words it was read from, and the part the page's own title block names where it
names one. A finding no part can be given stays in the list, visible, as "unassigned". The
record carries this list as `summary["reader_findings"]`, and the retention trace audits each
transition from it: finding -> built part record -> costed record -> calculated workbook cell.

What is read, per page: the title block's identity, material and gauge, finish and quantity;
the overall figures ("1168 O/A"); hole callouts with their counts ("(5x) Ø3.4 THRU"); countersinks
("Ø6.3 x 90°"); threads ("(9x) M3x0.5"); section callouts (a tube profile with its length or
pieces); the operations the sheet's words state. From the parts list: each row with its
quantity, its description and whether its code is a purchase. Nothing here infers: a finding is
a reading with its words, or it is not a finding.

The pass is pure and reads what the scan already holds; it never calls a model and it changes
nothing on the pages or the parts.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA = "reader_findings.v1"

_OA = re.compile(r"(?<![\d.])(\d{1,5}(?:\.\d+)?)\s*O\s*/?\s*A(?![A-Z])")
# "(5x)n3.4THRU", "(5X) Ø3.4 THRU", "Ø10 THRU", "n10THRU" (pdfplumber renders Ø as n or w).
_HOLE = re.compile(r"(?:\(\s*(?P<count>\d{1,3})\s*[xX]\s*\)\s*)?(?<![A-Z])[nwØ⌀]\s*(?P<dia>\d{1,3}(?:\.\d+)?)\s*THRU",
                   re.IGNORECASE)
# A count printed AFTER the callout: "M8x1.25 THRU BOTTOM FACE (4 TOTAL)", "Ø10 THRU ... (11 TOTAL)".
_TOTAL = re.compile(r"\(\s*(\d{1,3})\s*TOTAL\s*\)", re.IGNORECASE)
# What the hole is for, where the callout says ("FOR PUDDLE WELD").
_PURPOSE = re.compile(r"\bFOR\s*([A-Z]+(?:\s*[A-Z]+){0,2})", re.IGNORECASE)
# "wn6.3X90.00°": a countersink diameter and its included angle.
_CSK = re.compile(r"[nwØ⌀]\s*(?P<dia>\d{1,3}(?:\.\d+)?)\s*[xX]\s*(?P<angle>82|90|100|120)(?:\.0+)?\s*°")
# "(9X) M3X0.5", "4x M8x1.25", "M6 x 1.0 TAPPED".
_THREAD = re.compile(r"(?:\(\s*(?P<count>\d{1,3})\s*[xX]\s*\)\s*|(?P<count2>\d{1,3})\s*[xX]\s+)?"
                     r"(?<![A-Z0-9])M(?P<dia>\d{1,2})\s*[xX]\s*(?P<pitch>\d\.\d{1,2})(?!\s*MM)", re.IGNORECASE)
_CALLOUT_START = re.compile(r"(?<![A-Z])[nwØ⌀]\s*\d{1,3}(?:\.\d+)?\s*THRU|(?<![A-Z0-9])M\d{1,2}\s*[xX]\s*\d\.\d", re.IGNORECASE)


def _trailing(text: str, end: int) -> str:
    """The words after a callout up to the next callout (at most 80 characters)."""
    nxt = _CALLOUT_START.search(text, end)
    return text[end: min(nxt.start() if nxt else len(text), end + 80)]
_OPS = ("welding", "tapping", "countersinking", "folding", "drilling", "deburring")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _text(page: Mapping[str, Any]) -> str:
    for k in ("pdfplumber_text", "normalized_text", "pypdf_text"):
        t = page.get(k)
        if t and str(t).strip():
            return str(t)
    rt = page.get("region_text") if isinstance(page.get("region_text"), Mapping) else {}
    return " ".join(str(rt.get(k) or "") for k in ("title_block", "bom", "notes", "revision", "general"))


def _title_block_text(page: Mapping[str, Any]) -> str:
    rt = page.get("region_text") if isinstance(page.get("region_text"), Mapping) else {}
    return str(rt.get("title_block") or "")


def _listed(summary: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The parts-list rows by part number: identity for the pages, and findings of their own."""
    out: Dict[str, Dict[str, Any]] = {}
    da = summary.get("document_analysis") if isinstance(summary.get("document_analysis"), Mapping) else {}
    for row in (da.get("bom_rows") or []):
        if isinstance(row, Mapping) and row.get("part_number"):
            out.setdefault(" ".join(str(row["part_number"]).split()).upper(), dict(row))
    for p in summary.get("parts") or []:
        if isinstance(p, Mapping) and p.get("part_number"):
            out.setdefault(" ".join(str(p["part_number"]).split()).upper(),
                           {"part_number": p["part_number"], "description": p.get("description"),
                            "quantity": p.get("quantity")})
    return out


def _identity(page: Mapping[str, Any], listed: Mapping[str, Mapping[str, Any]]) -> Optional[str]:
    """The listed part this page's own title block names, or None."""
    try:
        import part_index as pi
        hit = pi._composite_title_block_identity(dict(page), {}, {k: dict(v) for k, v in listed.items()})
        if hit:
            return " ".join(str(hit[0]).split()).upper()
    except Exception:                                                # noqa: BLE001
        pass
    tb = re.sub(r"\s+", "", _title_block_text(page).upper())
    hits = [pn for pn in listed if re.sub(r"\s+", "", pn) and re.sub(r"\s+", "", pn) in tb]
    return hits[0] if len(hits) == 1 else None


def _bom_page(summary: Mapping[str, Any], row: Mapping[str, Any]) -> Any:
    sheet = str(row.get("bom_sheet") or "")
    m = re.search(r"#(\d+)$", sheet)
    if m:
        return int(m.group(1))
    return row.get("page") or row.get("page_number")


def capture(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """Every finding the deterministic reader made, page by page, before the build. Pure."""
    items: List[Dict[str, Any]] = []
    listed = _listed(summary)
    n = 0

    def add(**f: Any) -> None:
        nonlocal n
        n += 1
        f.setdefault("units", None)
        f.setdefault("part", None)
        f.setdefault("source", "pdf_text")
        items.append({"id": f"F{n}", **f})

    pages = [p for p in (summary.get("pages") or []) if isinstance(p, Mapping)]
    for page in pages:
        pno = page.get("page_number")
        text = _text(page)
        if not text.strip():
            continue
        upper = text.upper()
        part = _identity(page, listed)
        tb = _title_block_text(page)
        if part:
            add(page=pno, part=part, kind="identity", value=part, words=tb[:160].strip(),
                source="title_block")
        try:
            import part_index as pi
            gm = pi._title_block_gauge_and_material(tb)
        except Exception:                                            # noqa: BLE001
            gm = None
        if gm:
            add(page=pno, part=part, kind="material", value=gm.get("material"), words=gm.get("printed"),
                source="title_block")
            if gm.get("thickness_mm") is not None and not gm.get("section"):
                add(page=pno, part=part, kind="thickness", value=gm["thickness_mm"], units="mm",
                    words=gm.get("printed"), source="title_block")
            if gm.get("section"):
                add(page=pno, part=part, kind="section_profile", value=gm["section"], units="mm",
                    words=gm.get("printed"), source="title_block")
        try:
            import finish_rules as fr
            fams = fr.finish_families(tb) if tb else set()
        except Exception:                                            # noqa: BLE001
            fams = set()
        for fam in sorted(fams):
            if fam == "bare":
                continue
            tok = next((t for t in (fr.FINISH_FAMILIES.get(fam) or ())
                        if re.search(r"\b" + re.escape(t).replace(r"\ ", r"\s+"), tb.upper())), fam)
            m = re.search(r"\S*" + re.escape(tok).replace(r"\ ", r"\s+") + r"\S*", tb.upper())
            add(page=pno, part=part, kind="finish", value=fam, words=(m.group(0) if m else tok),
                source="title_block")
        oa = [(float(m.group(1)), m.group(0).strip()) for m in _OA.finditer(upper)]
        if oa:
            add(page=pno, part=part, kind="overall", value=[v for v, _w in oa], units="mm",
                words=", ".join(w for _v, w in oa))
        for m in _HOLE.finditer(text):
            tail = _trailing(text, m.end())
            tot = _TOTAL.search(tail)
            purpose = _PURPOSE.search(tail)
            count = int(m.group("count") or (tot.group(1) if tot else 0) or 1)
            v = {"diameter_mm": float(m.group("dia")), "count": count,
                 "count_printed": bool(m.group("count") or tot)}
            if purpose:
                v["purpose"] = " ".join(purpose.group(1).split()).lower()
            cut = max([x.end() for x in (tot, purpose) if x] or [0])
            add(page=pno, part=part, kind="hole", value=v, units="mm",
                words=" ".join((m.group(0) + " " + tail[:cut]).split())[:120])
        for m in _CSK.finditer(text):
            add(page=pno, part=part, kind="countersink",
                value={"diameter_mm": float(m.group("dia")), "angle_deg": float(m.group("angle"))},
                units="mm", words=m.group(0).strip())
        for m in _THREAD.finditer(text):
            tail = _trailing(text, m.end())
            tot = _TOTAL.search(tail)
            count = int(m.group("count") or m.group("count2") or (tot.group(1) if tot else 0) or 1)
            add(page=pno, part=part, kind="thread",
                value={"thread": f"M{m.group('dia')}x{m.group('pitch')}", "count": count,
                       "count_printed": bool(m.group("count") or m.group("count2") or tot),
                       "through": bool(re.match(r"\s*THRU", tail, re.IGNORECASE))},
                words=" ".join((m.group(0) + " " + tail[:tot.end() if tot else 0]).split())[:120])
        try:
            from section_profile import detect_section_stock
            sec = detect_section_stock(text)
        except Exception:                                            # noqa: BLE001
            sec = None
        if sec and sec.get("a"):
            add(page=pno, part=part, kind="section_callout",
                value={k: sec.get(k) for k in ("a", "b", "t", "length_mm", "cut_lengths_mm") if sec.get(k) is not None},
                units="mm", words=str(sec.get("source_text") or sec.get("length_printed") or "")[:120])
        try:
            from extractor_patterns import operation_evidence_in_text
            ev = operation_evidence_in_text(text, list(_OPS)) or {}
        except Exception:                                            # noqa: BLE001
            ev = {}
        for op, words in ev.items():
            add(page=pno, part=part, kind="operation", value=op, words=str(words)[:120])
    for pn, row in listed.items():
        try:
            from bought_in_policy import bought_in_reason
            why = bought_in_reason({"part_number": row.get("part_number"), "description": row.get("description"),
                                    "page_roles": row.get("page_roles") or []})
        except Exception:                                            # noqa: BLE001
            why = ""
        add(page=_bom_page(summary, row), part=pn, kind="bom_row",
            value={"quantity": _num(row.get("quantity")), "description": row.get("description"),
                   "purchase": why or None},
            words=f"{row.get('part_number')} {row.get('description') or ''} x{row.get('quantity')}".strip(),
            source="bom_table")
    return {"schema": SCHEMA, "captured": "scan", "items": items, "pages_read": len(pages),
            "unassigned": sum(1 for i in items if not i.get("part"))}


def by_part(findings: Mapping[str, Any]) -> Dict[Optional[str], List[Dict[str, Any]]]:
    out: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for i in findings.get("items") or []:
        out.setdefault(i.get("part"), []).append(dict(i))
    return out


# The work a hole, a thread or a countersink asks of its part, and the operation that does it.
_FEATURE_OP = {"thread": "tapping", "countersink": "countersinking"}


def attach_stated_features(summary: Mapping[str, Any]) -> int:
    """Put each hole, thread and countersink the reader found on a part's own sheet on that
    part's record, with its count, page and words (SCRUM-194). A feature already on the record
    at the same size is not added twice. The work it asks for is put on the part where the
    record lacks it, sourced to the sheet's note: a thread is tapped, a countersink sunk, and a
    hole through section stock (which no laser cuts) is drilled. Returns features attached."""
    findings = summary.get("reader_findings") if isinstance(summary.get("reader_findings"), Mapping) else {}
    parts = {" ".join(str(p.get("part_number") or "").split()).upper(): p
             for p in ((summary.get("manufacturing_writeup") or {}).get("parts") or []) if isinstance(p, dict)}
    n = 0
    for f in findings.get("items") or []:
        kind = f.get("kind")
        if kind not in ("hole", "thread", "countersink"):
            continue
        part = parts.get(" ".join(str(f.get("part") or "").split()).upper())
        if part is None:
            continue
        feat = {"kind": kind, **dict(f.get("value") or {}), "page": f.get("page"), "words": f.get("words"),
                "finding": f.get("id"), "source": "drawing_notes"}
        have = part.setdefault("stated_features", [])
        key = (kind, feat.get("diameter_mm"), feat.get("thread"), feat.get("page"))
        if any((h.get("kind"), h.get("diameter_mm"), h.get("thread"), h.get("page")) == key for h in have):
            continue
        have.append(feat)
        n += 1
        if kind == "hole" and feat.get("diameter_mm"):
            sizes = part.setdefault("hole_sizes_mm", [])
            if not any(_num(x) == feat["diameter_mm"] for x in sizes):
                sizes.append(feat["diameter_mm"])
        op = _FEATURE_OP.get(kind)
        if kind == "hole" and (part.get("section_stock") or part.get("section_stock_on_members")):
            op = "drilling"
        if op:
            ops = part.setdefault("textual_operations", [])
            if op not in ops:
                ops.append(op)
            part.setdefault("operation_sources", {}).setdefault(op, "drawing_notes")
            part.setdefault("operation_evidence", {}).setdefault(op, str(f.get("words") or "")[:120])
    return n
