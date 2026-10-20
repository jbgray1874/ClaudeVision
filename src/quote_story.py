"""quote_story.py — the two pages after the price: how SDI read the enquiry, and how the price
is built (D-504).

James Gray, 13 Oct 2026: the one-off K-Wellness showcase — the customer's own words beside
what SDI concluded from them, one part followed from sketch to priced line, and the cost model
across the quantities — is what a quotation should look like, "auto-generated as part of the
general process, with as much detail as possible, two or three pages".

THE PRICE PAGE IS UNTOUCHED. The quotation's first page — the figure, the release gate, the
customer/portal naming, the print block — is client_quote_html's and stays exactly as it was.
These pages follow it and add what the showcase showed, built from the run's own record for
EVERY job, never written by hand:

  page 2  How we read your enquiry — what the pack held and what the run produced; the chain
          from what was read, through what was concluded and how SDI would make it, to the
          price; and evidence cards: the pack's OWN words (quoted verbatim, page named, the
          page shown), what was concluded, and where it landed on the costed bill.
  page 3  From drawing to price — one made part followed end to end (blank, nest, cut, form,
          finish, the workbook's own sum for its material line); the price at each quantity
          split into material, set-up, running work and overheads, so it is plain why the unit
          price falls with volume; one-off project costs; and the basis the price rests on.

WHAT IS QUOTED IS QUOTED. A card's "you wrote / your drawing says" box holds a line found in
the pack's own text; a topic with no such line gets no box rather than a paraphrase. Every
figure comes from the workbook's calculated rows (final_estimate) or the costed record — the
same numbers the Estimate sheet holds.

CUSTOMER LANGUAGE, NO WORKINGS. Nothing here names an open question, an internal check or an
engine field: the customer's own part codes and words, SDI's departments, and money.
Switches in config.QUOTE_DOCUMENT; the cost split by quantity is one of them
(show_cost_structure) because it shows the shape of SDI's costs to the reader.
"""
from __future__ import annotations

import base64
import html as _html
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import config as _config                                         # noqa: WPS433
except Exception:                                                    # noqa: BLE001
    _config = None


def _cfg() -> Dict[str, Any]:
    base = {
        "story_pages": True, "show_cost_structure": True, "evidence_cards": 4,
        "page_thumbnails": True, "thumbnail_zoom": 0.55, "max_pages_read": 60,
    }
    base.update(dict(getattr(_config, "QUOTE_DOCUMENT", {}) or {}))
    return base


def _esc(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _gbp(v: Any, dp: int = 2) -> str:
    f = _num(v)
    return "—" if f is None else f"£{f:,.{dp}f}"


def _g(v: Any) -> str:
    f = _num(v)
    if f is None:
        return "—"
    return f"{f:,.0f}" if abs(f - round(f)) < 1e-9 else f"{f:,.2f}".rstrip("0").rstrip(".")


# ── WHAT THE RUN RECORDED ─────────────────────────────────────────────────────────────

def _final(summary: Dict[str, Any]) -> Dict[str, Any]:
    fe = summary.get("final_estimate")
    if not isinstance(fe, dict):
        fe = (summary.get("estimate_summary") or {}).get("final_estimate")
    return fe if isinstance(fe, dict) else {}


def _pdf_sources(summary: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The pack's PDFs, as (name, path), in the order the run read them."""
    out: List[Tuple[str, str]] = []
    seen = set()

    def _add(name: Any, path: Any) -> None:
        p = str(path or "")
        if p and p.lower().endswith(".pdf") and p not in seen and os.path.exists(p):
            seen.add(p)
            out.append((str(name or os.path.basename(p)), p))
    for d in summary.get("job_source_pdfs") or []:
        if isinstance(d, dict):
            _add(d.get("name"), d.get("path"))
    for p in list(summary.get("scanned_documents") or []) + list(summary.get("staged_inputs") or []):
        _add(os.path.basename(str(p)), p)
    pp = summary.get("primary_pdf") or {}
    if isinstance(pp, dict):
        _add(pp.get("name"), pp.get("path"))
    return out


def _pdf_blocks(path: str, page: int) -> List[str]:
    """A page's text as the PDF lays it out in blocks — a callout, a note, a paragraph — so a
    label set over two lines ("Side shelves" / "(Mirrored) x10") is quoted whole."""
    if not (path and os.path.exists(path)):
        return []
    try:
        import fitz                                                  # noqa: WPS433
        doc = fitz.open(path)
        try:
            if not 0 < int(page) <= doc.page_count:
                return []
            blocks = doc.load_page(int(page) - 1).get_text("blocks") or []
        finally:
            doc.close()
    except Exception:                                                # noqa: BLE001
        return []
    return [" ".join(str(b[4]).split()) for b in blocks
            if len(b) > 6 and b[6] == 0 and str(b[4]).strip()]


def _page_texts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every page's own text, with where it came from. The run's saved page text first; the
    PDFs themselves where the run kept none (a render-led read keeps no pdfplumber pages).
    Each page also carries the PDF's own text blocks where the file is at hand."""
    pages: List[Dict[str, Any]] = []
    for i, p in enumerate(summary.get("pages") or []):
        if not isinstance(p, dict):
            continue
        txt = str(p.get("pdfplumber_text") or p.get("normalized_text") or "")
        path = str(p.get("source_pdf_path") or "")
        pages.append({"text": txt, "path": path, "doc": os.path.basename(path),
                      "page": int(p.get("page_number") or i + 1),
                      "role": str(((p.get("page_role") or {}).get("primary_role")
                                   if isinstance(p.get("page_role"), dict) else "") or "")})
    if any(pg["text"].strip() for pg in pages):
        for pg in pages:
            pg["blocks"] = _pdf_blocks(pg["path"], pg["page"])
        return pages
    pages = []
    try:
        import fitz                                                  # noqa: WPS433
    except Exception:                                                # noqa: BLE001
        return pages
    limit = int(_cfg().get("max_pages_read") or 60)
    for name, path in _pdf_sources(summary):
        try:
            doc = fitz.open(path)
        except Exception:                                            # noqa: BLE001
            continue
        try:
            for i in range(min(doc.page_count, limit - len(pages))):
                pg = doc.load_page(i)
                pages.append({"text": pg.get_text() or "", "path": path,
                              "doc": name, "page": i + 1, "role": "",
                              "blocks": [" ".join(str(b[4]).split())
                                         for b in (pg.get_text("blocks") or [])
                                         if len(b) > 6 and b[6] == 0 and str(b[4]).strip()]})
        finally:
            doc.close()
        if len(pages) >= limit:
            break
    return pages


_BOILERPLATE = re.compile(
    r"©|copyright|all rights reserved|confidential|proprietary|do not scale|unless otherwise|"
    r"tolerance|third angle|projection|drawn by|checked by|approved|sheet \d+ of|dimensions in|"
    r"for internal use|scale\s*[:1]|www\.|https?://|@|property of|unless stated", re.I)

# The topics a quotation's evidence is about, and the words in a pack that speak to each.
_TOPICS: Dict[str, Dict[str, Any]] = {
    "parts": {"title": "The parts",
              "words": r"\bx\s?\d+\b|\b\d+\s*(?:off|no\.?)\b|parts? list|exploded|qty"},
    "material": {"title": "Material and gauge",
                 "words": r"\bsteel\b|\balumin|\bacrylic|\bperspex|\bmdf\b|\bplywood|"
                          r"\bstainless|\bgauge\b|\bcr4\b|\bzintec|\bsheet\b|\d+(?:\.\d+)?\s*mm\s+(?:thick|steel|ms|cr)"},
    "joints": {"title": "How it goes together",
               "words": r"\bweld|\brivet|\bbolt|\bscrew|\bglue|\bbond|\badhesive|\bfix(?:ing|ed)|"
                        r"\bhook|\bslot(?:ted)?\b|\bclip"},
    "finish": {"title": "Finish",
               "words": r"\bpowder|\bral\s?\d{4}|\bpaint|\bfinish|\bcoat|\banodis|\bzinc|\bpolish|"
                        r"\bcolou?r"},
}


def _lines(page: Dict[str, Any]) -> List[str]:
    """What a page says, in quotable pieces: its text blocks where the PDF gives them (a long
    block split at its sentences and bullets), else its lines with a count on a line of its
    own joined to the label above it ("Front shelves" / "x5" -> "Front shelves x5")."""
    blocks: List[str] = []
    for b in (page.get("blocks") or []):
        # A sentence the layout broke over two blocks ("Shelf tray would have welded" / "or
        # riveted hooked brackets.") is one sentence again.
        if b and blocks and blocks[-1][-1:] not in ".!?:;" and b[:1].islower():
            blocks[-1] = f"{blocks[-1]} {b}"
        elif b:
            blocks.append(b)
    if blocks:
        out_b: List[str] = []
        for b in blocks:
            if len(b) <= 180:
                out_b.append(b)
                continue
            out_b.extend(x.strip(" •-–") for x in re.split(r"(?<=[.!?])\s+|\s*•\s*", b)
                         if len(x.strip(" •-–")) > 3)
        return out_b
    raw = [" ".join(l.split()) for l in str(page.get("text") or "").splitlines()]
    out: List[str] = []
    for l in raw:
        if not l:
            continue
        if out and re.fullmatch(r"(?:\(?[a-z ]*\)?\s*)?x\s?\d+", l, re.I):
            out[-1] = f"{out[-1]} {l}"
            continue
        out.append(l)
    return out


# Material words a pack may use. A line naming one the bill does not carry (an earlier
# design's MDF, a competitor's plastic) is not evidence for what was priced.
_MATERIAL_WORDS = ("steel", "alumin", "acrylic", "perspex", "mdf", "plywood", "stainless",
                   "plastic", "timber", "wood", "glass", "foamex", "dibond", "polycarbonate")


def _legend_free(page: Dict[str, Any]) -> str:
    """The page's text with the drawing border's specification legend taken out (the
    engine's own reading, extractor_patterns) — a standing note in the template is not
    something this enquiry said. Upper case, single-spaced, for containment tests."""
    if "_kept" not in page:
        text = " ".join(page.get("blocks") or []) or str(page.get("text") or "")
        try:
            from extractor_patterns import strip_specification_legend   # noqa: WPS433
            text = strip_specification_legend(text)
        except Exception:                                            # noqa: BLE001
            pass
        page["_kept"] = " ".join(text.split()).upper()
    return page["_kept"]


def _quotable(line: str, page: Dict[str, Any]) -> bool:
    return (not _BOILERPLATE.search(line)
            and " ".join(line.split()).upper() in _legend_free(page))


def _quote_for(topic: str, pages: List[Dict[str, Any]], used: set,
               prefer: Iterable[str] = (), avoid: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """The pack's own line that best speaks to a topic, verbatim, with its page — or None.

    `prefer` are words of what the bill actually charges (its material, its joints, its
    finish); a line naming them is the evidence for what was priced. `avoid` are words of
    what the bill does not carry; a line naming them describes something else."""
    rx = re.compile(_TOPICS[topic]["words"], re.I)
    pre = [w.lower() for w in prefer if w]
    avo = [w.lower() for w in avoid if w]
    best, best_score = None, 0.0
    for pg in pages:
        for line in _lines(pg):
            if line in used or not _quotable(line, pg):
                continue
            hits = len(rx.findall(line))
            words = len(line.split())
            if not hits or words < 2:
                continue
            score = hits * 2 + min(words, 12) / 6.0 - (0.6 if words > 30 else 0.0)
            low = line.lower()
            score += 3.0 * sum(1 for w in pre if w in low)
            score -= 4.0 * sum(1 for w in avo if w in low)
            if (pg.get("role") or "") == "assembly":
                score += 0.5
            if ("page", pg["doc"], pg["page"]) in used:
                score -= 1.5          # a different page each, where the pack allows
            if score > best_score:
                best, best_score = {"text": line[:180], "page": pg["page"], "doc": pg["doc"],
                                    "path": pg["path"]}, score
    if best:
        used.add(best["text"])
        used.add(("page", best["doc"], best["page"]))
    return best


_COUNT_LABEL = re.compile(r"^(?=.*[a-z]).{2,60}?\s(?:x|×)\s?\d{1,3}$", re.I)


def _count_labels_quote(pages: List[Dict[str, Any]], used: set,
                        most: int = 4) -> Optional[Dict[str, Any]]:
    """A labelled view's own callouts ("Front shelves x5") — the page that carries most of
    them, its first few quoted verbatim and joined, as a parts list the customer drew."""
    best: Optional[Tuple[Dict[str, Any], List[str]]] = None
    for pg in pages:
        labels = [l for l in _lines(pg) if _COUNT_LABEL.match(l) and _quotable(l, pg)
                  and l not in used]
        if len(labels) >= 2 and (best is None or len(labels) > len(best[1])):
            best = (pg, labels)
    if not best:
        return None
    pg, labels = best
    shown = labels[:most]
    used.update(shown)
    used.add(("page", pg["doc"], pg["page"]))
    return {"text": "” · “".join(shown), "page": pg["page"], "doc": pg["doc"],
            "path": pg["path"], "labels": len(labels)}


def _parts_list_quote(pages: List[Dict[str, Any]], used: set, codes: Iterable[str],
                      most: int = 3) -> Optional[Dict[str, Any]]:
    """A drawing's own parts list — the rows naming the bill's part codes, from the page that
    carries most of them, the first few quoted verbatim and joined."""
    want = [c.upper() for c in codes if c and len(c) >= 4]
    if not want:
        return None
    best: Optional[Tuple[Dict[str, Any], List[str]]] = None
    for pg in pages:
        rows = [l for l in _lines(pg) if len(l) <= 120 and l not in used and _quotable(l, pg)
                and any(c in l.upper() for c in want)]
        if rows and (best is None or len(rows) > len(best[1])):
            best = (pg, rows)
    if not best:
        return None
    pg, rows = best
    shown = rows[:most]
    used.update(shown)
    used.add(("page", pg["doc"], pg["page"]))
    return {"text": "” · “".join(shown), "page": pg["page"], "doc": pg["doc"],
            "path": pg["path"]}


def _page_image(path: str, page: int, zoom: float) -> Optional[str]:
    """One pack page as a small JPEG data URI — the page the quote came from."""
    if not (path and os.path.exists(path)):
        return None
    try:
        import fitz                                                  # noqa: WPS433
        doc = fitz.open(path)
        try:
            pix = doc.load_page(max(0, int(page) - 1)).get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            try:
                data = pix.tobytes("jpg", jpg_quality=72)
                mime = "jpeg"
            except Exception:                                        # noqa: BLE001
                data, mime = pix.tobytes("png"), "png"
        finally:
            doc.close()
        return f"data:image/{mime};base64," + base64.b64encode(data).decode("ascii")
    except Exception:                                                # noqa: BLE001
        return None


# ── THE COSTED JOB, IN THE TERMS A CUSTOMER READS ──────────────────────────────────────

def _is_bought(p: Dict[str, Any]) -> bool:
    """The codebase's one make/buy predicate, with the concept read's own classing beside it."""
    if str(p.get("concept_kind") or "") in ("bought_in", "graphic"):
        return True
    try:
        from bought_in_policy import is_bought_in                    # noqa: WPS433
        return bool(is_bought_in(p))
    except Exception:                                                # noqa: BLE001
        roles = {str(r).lower() for r in (p.get("page_roles") or [])}
        mat = str(p.get("normalized_material") or "").upper()
        return bool(p.get("is_bought_in") or "bought_in" in roles
                    or mat in ("BOUGHT_IN", "BOUGHT IN"))


def _freight_codes() -> Tuple[str, ...]:
    try:
        from quantity_sweep import _FREIGHT_CODES                    # noqa: WPS433
        return tuple(_FREIGHT_CODES)
    except Exception:                                                # noqa: BLE001
        return ("PACKAGING", "DELIVERY")


def _is_line_item(p: Dict[str, Any]) -> bool:
    """A part of the product, not a commercial line riding on the bill (packaging, delivery,
    a project cost, a plater's freight) and not a consumable charged by weight."""
    if not isinstance(p, dict):
        return False
    if (p.get("_commercial_placeholder") or p.get("project_cost_line")
            or str(p.get("source") or "") == "commercial_placeholder"
            or p.get("_consumable_qty_unknown")):
        return False
    code = str(p.get("part_number") or "").strip().upper()
    return not any(code.startswith(c) for c in _freight_codes())


def _is_assembly(p: Dict[str, Any]) -> bool:
    return (str(p.get("_canonical_kind") or "").lower() == "assembly"
            or "assembly" in {str(r).lower() for r in (p.get("page_roles") or [])}
            and not _num(p.get("blank_length_mm")))


def _qty(p: Dict[str, Any]) -> float:
    return _num(p.get("quantity")) or 1.0


def _material_name(p: Dict[str, Any]) -> str:
    m = str(p.get("normalized_material") or "").replace("_", " ").strip()
    return m.title() if m else ""


def _code_in(text: Any) -> str:
    return str(text or "").strip().split()[0] if str(text or "").strip() else ""


# (key in the operation's own name, the department as a customer reads it). The list order is
# the shop order a part travels in; a more specific key sits before a word it contains
# ("Dress Welds" is dressing, not welding).
_DEPT_ORDER = [("laser", "Laser"), ("punch", "Punch"), ("guillot", "Guillotine"), ("saw", "Saw"),
               ("cnc", "CNC"), ("rout", "Route"), ("fold", "Fold"), ("bend", "Bend"),
               ("press", "Press"), ("dress", "Dress"), ("weld", "Weld"), ("drill", "Drill"),
               ("tap", "Tap"), ("insert", "Insert"), ("machin", "Machine"), ("glue", "Glue"),
               ("edg", "Edge"), ("p.coat", "Powder coat"), ("powder", "Powder coat"),
               ("paint", "Paint"), ("spray", "Spray"), ("print", "Print"), ("lamin", "Laminate"),
               ("manual", "Hand work"), ("assembl", "Assemble"), ("pack", "Pack")]


# The order a part travels the shop in, which is the order a route is told in.
_ROUTE_ORDER = ["Laser", "Punch", "Guillotine", "Saw", "CNC", "Route", "Fold", "Bend", "Press",
                "Weld", "Dress", "Drill", "Tap", "Insert", "Machine", "Powder coat", "Paint",
                "Spray", "Print", "Laminate", "Glue", "Edge", "Hand work", "Assemble", "Pack"]


def _dept_label(operation: str) -> Tuple[int, str]:
    """(shop order, department as a customer reads it) for a labour row's operation."""
    low = str(operation or "").lower()
    for key, label in _DEPT_ORDER:
        if key in low:
            return _ROUTE_ORDER.index(label), label
    return len(_ROUTE_ORDER), str(operation or "").split("(")[0].strip().title()


def _labour_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The labour block's charged rows — not its total lines, which carry the block's sum."""
    fe = _final(summary)
    rows = [r for r in (fe.get("labour_rows") or []) if isinstance(r, dict)
            and (_num(r.get("total_value_gbp")) or 0) > 0
            and not re.match(r"\s*total\b", str(r.get("operation") or ""), re.I)]
    if rows:
        return rows
    wl = summary.get("workbook_labour") or (summary.get("estimate_summary") or {}).get("workbook_labour")
    return [{"operation": r.get("wb_operation"), "part_numbers": r.get("part_numbers"),
             "description": f"{r.get('thickness_mm') or ''}mm {r.get('material') or ''}".strip()}
            for r in ((wl or {}).get("rows") or []) if isinstance(r, dict)]


def _parts_on(row: Dict[str, Any]) -> List[str]:
    pn = row.get("part_numbers")
    if isinstance(pn, (list, tuple)):
        return [str(x) for x in pn]
    return [s.strip() for s in re.split(r"[,;]", str(pn or "")) if s.strip()]


def _material_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The material blocks' charged rows — a row with a quantity a unit; the blocks' caption
    and total lines ("Sheet Steel", "Total Material Cost") carry none."""
    return [r for r in (_final(summary).get("material_rows") or []) if isinstance(r, dict)
            and (_num(r.get("qty_per_unit")) or 0) > 0]


def _money(facts: Dict[str, Any], value: float, text: str, without: str) -> str:
    """A per-unit figure at the price's markup — or the words alone, when the record's figures
    do not give the price the first page shows (figures_agree)."""
    if not facts.get("agree"):
        return without
    return text.replace("{}", _gbp(value * float(facts.get("markup") or 1.0)))


def job_facts(summary: Dict[str, Any], parts: List[Dict[str, Any]],
              qty: int) -> Dict[str, Any]:
    """What the pack held and what the run produced, counted from the run's own record."""
    parts = [p for p in parts if _is_line_item(p)]
    made = [p for p in parts if not _is_bought(p) and not _is_assembly(p)]
    bought = [p for p in parts if _is_bought(p) and not _is_assembly(p)]
    pages = _page_texts(summary)
    srcs = _pdf_sources(summary)
    names = [n.lower() for n, _ in srcs] + [str(x).lower() for x in
                                            (summary.get("scanned_documents") or [])]
    dxf = sum(1 for n in names if n.endswith(".dxf"))
    models = sum(1 for n in names if n.endswith((".sldprt", ".sldasm", ".step", ".stp")))
    bom_rows = ((summary.get("document_analysis") or {}).get("bom_rows") or [])
    concept = summary.get("concept_read") if isinstance(summary.get("concept_read"), dict) else {}
    labour = _labour_rows(summary)
    decisions = [d for d in ((summary.get("estimate_summary") or {}).get("canonical_route_shadow")
                             or {}).get("decisions") or [] if isinstance(d, dict)
                 and str(d.get("status")) == "required"]
    # The departments the sheet charged; where no calculated rows were stamped, the route's
    # own required operations (a name no department answers to is left out, not guessed).
    depts = sorted({_dept_label(r.get("operation") or r.get("department")) for r in labour}
                   or {t for t in (_dept_label(str(d.get("operation") or "").replace("_", " "))
                                   for d in decisions) if t[0] < len(_ROUTE_ORDER)},
                   key=lambda t: t[0])
    sweep = [r for r in ((summary.get("quantity_sweep") or {}).get("rows") or [])
             if isinstance(r, dict) and _num(r.get("quantity"))]
    by_mat: Dict[str, Dict[str, Any]] = {}
    for p in made:
        t = _num(p.get("normalized_thickness_mm"))
        key = f"{_material_name(p) or 'Material'}" + (f" {t:g} mm" if t else "")
        rec = by_mat.setdefault(key, {"lines": 0, "pieces": 0.0})
        rec["lines"] += 1
        rec["pieces"] += _qty(p)
    # Which parts each department works on: the sheet's rows, else the route's decisions.
    by_dept: Dict[str, set] = {}
    for r in labour:
        by_dept.setdefault(_dept_label(r.get("operation") or "")[1], set()).update(_parts_on(r))
    if not labour:
        for d in decisions:
            lab = _dept_label(str(d.get("operation") or "").replace("_", " "))
            if lab[0] < len(_ROUTE_ORDER):
                by_dept.setdefault(lab[1], set()).update(
                    str(x) for x in (d.get("participants") or [d.get("target_id")]) if x)
    return {
        "parts_by_dept": by_dept,
        "pages": pages, "sources": srcs, "page_count": len(pages) or int(
            summary.get("page_count") or 0),
        "documents": len(srcs), "dxf": dxf, "models": models,
        "bom_rows": len(bom_rows), "concept": bool(concept.get("parts")),
        "brief_used": bool(concept.get("brief_used") or summary.get("enquiry_brief")),
        "lines": len([p for p in parts if not _is_assembly(p)]),
        "made": made, "bought": bought,
        "pieces": sum(_qty(p) for p in made) + sum(_qty(p) for p in bought),
        "made_pieces": sum(_qty(p) for p in made),
        "by_material": by_mat, "labour": labour, "departments": [d[1] for d in depts],
        "decisions": len(decisions), "sweep": sweep, "qty": qty,
    }


# ── THE EVIDENCE CARDS ────────────────────────────────────────────────────────────────

def _by_material(made: List[Dict[str, Any]]) -> List[Tuple[str, List[Tuple[str, float]]]]:
    """[(material, [(gauge, pieces), ...]), ...], most pieces first — "Mild steel — 1.5 mm
    ×54, 1 mm ×15, 2 mm ×9" rather than the material named once per gauge."""
    acc: Dict[str, Dict[str, float]] = {}
    for p in made:
        t = _num(p.get("normalized_thickness_mm"))
        gauges = acc.setdefault(_material_name(p) or "Sheet", {})
        key = f"{t:g} mm" if t else ""
        gauges[key] = gauges.get(key, 0.0) + _qty(p)
    out = [(m, sorted(g.items(), key=lambda kv: (kv[0] == "", -kv[1]))) for m, g in acc.items()]
    return sorted(out, key=lambda mg: -sum(n for _, n in mg[1]))


def _material_phrase(material: str, gauges: List[Tuple[str, float]]) -> str:
    """"mild steel — 1.5 mm ×54, 1 mm ×15", with pieces whose gauge was not set counted on
    the end ("…, 40 more"), never printed as a gauge-less "×40"."""
    sized = [(g, n) for g, n in gauges if g]
    rest = sum(n for g, n in gauges if not g)
    if not sized:
        return f"{material} ×{_g(rest)}"
    return (f"{material} — " + ", ".join(f"{g} ×{_g(n)}" for g, n in sized[:4])
            + (f", {_g(rest)} more" if rest else ""))


def _lower_words(text: str) -> str:
    """Lower case for running text, a code ("12645-01-03M") left as it is written."""
    return " ".join(w if re.search(r"\d", w) else w.lower() for w in str(text).split())


def _nice(text: Any) -> str:
    """A description as a sentence reads it: an all-capitals cell in sentence case."""
    t = " ".join(str(text or "").split())
    if t and t.upper() == t and any(c.isalpha() for c in t):
        t = " ".join(w if re.search(r"\d", w) else w.lower() for w in t.split())
        t = t[:1].upper() + t[1:]
    return t


def _rows_matching(labour: List[Dict[str, Any]], depts: Iterable[str]) -> List[Dict[str, Any]]:
    """The labour rows of the named departments, by the same reading the page labels them with."""
    want = set(depts)
    return [r for r in labour if _dept_label(r.get("operation") or "")[1] in want]


def _rows_value(rows: List[Dict[str, Any]]) -> float:
    return sum(_num(r.get("total_value_gbp")) or 0.0 for r in rows)


def evidence_items(summary: Dict[str, Any], facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The pack's own words → what was concluded → where it landed on the bill. A topic the pack
    says nothing about gets no quote box; its conclusion still stands, said as SDI's."""
    used: set = set()
    out: List[Dict[str, Any]] = []
    made, bought, labour = facts["made"], facts["bought"], facts["labour"]
    mats = _material_rows(summary)

    # 1 · the parts
    codes = [str(p.get("part_number") or "") for p in made + bought]
    q = (_count_labels_quote(facts["pages"], used)
         or _parts_list_quote(facts["pages"], used, codes)
         or _quote_for("parts", facts["pages"], used))
    top = sorted(made, key=lambda p: -(_num(p.get("unit_total_cost_gbp")) or 0))[:3]
    out.append({
        "topic": "parts", "title": _TOPICS["parts"]["title"], "saw": q,
        "concluded": (f"{len(made)} part{'s' if len(made) != 1 else ''} SDI makes "
                      f"({_g(facts['made_pieces'])} pieces a unit) and {len(bought)} bought "
                      f"in" + (f" — led by the " + ", the ".join(
                          _lower_words(_nice(p.get('description') or p.get('part_number')))
                          for p in top) if top else "") + "."),
        "bill": (f"{facts['lines']} lines on the bill: {_g(facts['made_pieces'])} made "
                 f"piece{'s' if facts['made_pieces'] != 1 else ''}"
                 + (f" and {_g(facts['pieces'] - facts['made_pieces'])} bought item"
                    f"{'s' if facts['pieces'] - facts['made_pieces'] != 1 else ''}"
                    if facts['pieces'] > facts['made_pieces'] else "") + " a unit"),
    })
    # 2 · material and gauge — quoted where the pack names what the bill is made of
    on_bill = " ".join([_material_name(p).lower() for p in made]
                       + [str(p.get("description") or "").lower() for p in bought])
    q = _quote_for("material", facts["pages"], used,
                   prefer=[w for w in _MATERIAL_WORDS
                           if w in " ".join(_material_name(p).lower() for p in made)],
                   avoid=[w for w in _MATERIAL_WORDS if w not in on_bill])
    groups = sorted(facts["by_material"].items(), key=lambda kv: -kv[1]["pieces"])
    sheet_val = sum(_num(r.get("total_value_gbp")) or 0 for r in mats
                    if str(r.get("block") or "") in ("steel", "other_sheet", "tube"))
    out.append({
        "topic": "material", "title": _TOPICS["material"]["title"], "saw": q,
        "concluded": ("Made from " + "; ".join(
            _material_phrase(m.lower() if i else m, gs)
            for i, (m, gs) in enumerate(_by_material(facts["made"])[:3])) + "."
            if groups else "No made parts — every line is bought in."),
        "bill": (_money(facts, sheet_val, "Sheet and section material {} a unit, nested on "
                        "SDI's stock", "Sheet and section material, nested on SDI's stock")
                 if sheet_val else "Material on the bill of materials"),
    })
    # 3 · joints — quoted where the pack names a joint the bill charges
    weld = _rows_matching(labour, ("Weld",))
    dress = _rows_matching(labour, ("Dress",))
    fix_rx = r"screw|bolt|rivet|nut|fix|washer|magnet|tape|adhesive"
    fix = [p for p in bought if re.search(fix_rx, str(p.get("description") or ""), re.I)]
    q = _quote_for("joints", facts["pages"], used,
                   prefer=(["weld"] if weld else []) + sorted({
                       m.group(0).lower() for p in fix
                       for m in re.finditer(fix_rx, str(p.get("description") or ""), re.I)}))
    welded = sorted(facts["parts_by_dept"].get("Weld") or ())
    if welded:
        concl = (f"Welded where the pack calls for it — {len(welded)} part line"
                 f"{'s' if len(welded) != 1 else ''} — and dressed after welding"
                 + (f"; {len(fix)} fixing line{'s' if len(fix) != 1 else ''} bought in" if fix else "")
                 + ".")
        bill = (_money(facts, _rows_value(weld) + _rows_value(dress),
                       "Weld and dress {} a unit", "Weld and dress rows on the bill")
                if weld else "Weld and dress on the route")
    else:
        concl = ("No welding — the parts are fixed together"
                 + (f" with {len(fix)} bought-in fixing line{'s' if len(fix) != 1 else ''}"
                    if fix else "") + ".")
        bill = (_money(facts, sum((_num(p.get('unit_total_cost_gbp')) or 0) for p in fix),
                       "Fixings {} a unit", "Fixings on the bill of materials")
                if fix else "Assembly on the bench")
    out.append({"topic": "joints", "title": _TOPICS["joints"]["title"], "saw": q,
                "concluded": concl, "bill": bill})
    # 4 · finish — quoted where the pack names the finish the bill charges
    coat = _rows_matching(labour, ("Powder coat", "Paint", "Spray"))
    coat_kinds = {k for k in ("Powder coat", "Paint", "Spray")
                  if facts["parts_by_dept"].get(k)}
    powder = [r for r in mats if re.search(r"powder|paint", str(r.get("description") or ""), re.I)]
    coated = sorted(set().union(*[facts["parts_by_dept"].get(k) or set() for k in coat_kinds])
                    if coat_kinds else set())
    colours = sorted({c for p in made for c in re.findall(r"RAL\s?\d{4}", " ".join(
        str(x) for x in (p.get("colours") or []) + [p.get("normalized_finish") or ""]), re.I)})
    q = _quote_for("finish", facts["pages"], used,
                   prefer=(["powder"] if "Powder coat" in coat_kinds else [])
                   + (["paint"] if coat_kinds & {"Paint", "Spray"} else [])
                   + [c.lower() for c in colours])
    if coated:
        how = "Powder coated" if "Powder coat" in coat_kinds else "Painted"
        concl = (f"{how}, priced by the area actually coated, across {len(coated)} "
                 f"part line{'s' if len(coated) != 1 else ''}"
                 + (f" in {len(colours)} colour{'s' if len(colours) != 1 else ''} "
                    f"({', '.join(c.upper() for c in colours)})" if colours else "")
                 + "; bought-in parts are not coated.")
        bill = (_money(facts, _rows_value(coat) + sum(_num(r.get('total_value_gbp')) or 0
                                                      for r in powder),
                       "Coating {} a unit", "Coating rows on the bill")
                if coat else "Coating on the route")
    else:
        concl = "No coating is charged — the parts are supplied as made."
        bill = "No finish line"
    out.append({"topic": "finish", "title": _TOPICS["finish"]["title"], "saw": q,
                "concluded": concl, "bill": bill})
    n = int(_cfg().get("evidence_cards") or 4)
    return out[:n]


# ── ONE PART, END TO END ──────────────────────────────────────────────────────────────

def _pack_words_for(description: str, pages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The pack's own short label for a part — the callout sharing most of its words with the
    part's description ("Slotted corner post x6" for SLOTTED CORNER POST), with its page."""
    want = {w for w in re.findall(r"[a-z]{4,}", str(description or "").lower())}
    if len(want) < 1:
        return None
    best, best_score = None, 0.0
    for pg in pages:
        for line in _lines(pg):
            if len(line) > 80 or not _quotable(line, pg):
                continue
            got = want & set(re.findall(r"[a-z]{4,}", line.lower()))
            if len(got) < min(2, len(want)):
                continue
            score = len(got) / len(want) + (0.5 if _COUNT_LABEL.match(line) else 0.0)
            if score > best_score:
                best, best_score = {"text": line, "page": pg["page"]}, score
    return best


def trace_part(summary: Dict[str, Any], facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The nested made part that travels through most departments (then the largest material
    line), followed from the pack to its priced line, in the workbook's own figures."""
    rows = [r for r in _material_rows(summary)
            if str(r.get("block") or "") in ("steel", "other_sheet")
            and (_num(r.get("qty_per_unit")) or 0) > 0
            and (_num(r.get("qty_per_sheet")) or 0) > 0 and (_num(r.get("total_value_gbp")) or 0) > 0]
    if not rows:
        return None

    def _route_len(r: Dict[str, Any]) -> int:
        c = _code_in(r.get("description"))
        return len({_dept_label(l.get("operation"))[1] for l in facts["labour"]
                    if c and c in _parts_on(l)})
    row = max(rows, key=lambda r: (_route_len(r), _num(r.get("total_value_gbp")) or 0))
    code = _code_in(row.get("description"))
    rec = next((p for p in facts["made"] if str(p.get("part_number") or "") == code), {})
    q = _num(row.get("qty_per_unit")) or _qty(rec)
    scrap = _num(row.get("scrap_pct"))
    scrap = scrap / 100.0 if scrap and scrap > 1 else (scrap or 0.0)
    value = _num(row.get("total_value_gbp")) or 0.0
    each = value / max(q, 1e-9) / (1.0 + scrap)
    per = _num(row.get("qty_per_sheet")) or 0
    sheet = each * per
    on = [r for r in facts["labour"] if code and code in _parts_on(r)]
    steps = []
    for r in sorted(on, key=lambda r: _dept_label(r.get("operation"))[0]):
        n_parts = len(_parts_on(r))
        steps.append({"op": _dept_label(r.get("operation"))[1],
                      "value": _num(r.get("total_value_gbp")),
                      "shared": n_parts - 1 if n_parts > 1 else 0})
    seen = str(rec.get("concept_seen") or rec.get("bom_sheet") or "").strip()
    desc = str(rec.get("description") or " ".join(str(row.get("description") or "").split()[1:]))
    return {
        "code": code, "description": desc, "qty": q, "seen": seen,
        "said": _pack_words_for(desc, facts["pages"]),
        "length": _num(row.get("length_mm")), "width": _num(row.get("width_mm")),
        "gauge": _num(row.get("gauge")) or _num(row.get("thickness_mm"))
        or _num(rec.get("normalized_thickness_mm")),
        "material": _material_name(rec) or "Sheet",
        "per_sheet": per, "scrap": scrap, "value": value, "each": each, "sheet": sheet,
        "steps": steps,
    }


# ── THE PRICE AT EACH QUANTITY, AND WHY IT FALLS ───────────────────────────────────────

def cost_model(summary: Dict[str, Any], facts: Dict[str, Any],
               markup: float = 1.0) -> List[Dict[str, Any]]:
    """Each quantity's unit price as material, set-up, running work and overheads.

    The set-up share is the sheet's own arithmetic taken apart (quantity_sweep.basis_from_rows:
    each labour row's set-up minutes at its department's rate, over the quantity) — read off
    each recalculated column where the sweep recorded it, and from the stamped rows otherwise.
    Running work is the rest of the labour figure. Overheads and terms are what the unit cell
    adds to material and labour. Every component is scaled by the same markup the price is,
    so the parts add up to the price shown."""
    sweep = facts["sweep"]
    pts = [(int(_num(r["quantity"])), _num(r.get("material")) or 0.0, _num(r.get("labour")) or 0.0,
            _num(r.get("unit")) or 0.0, _num(r.get("setup_per_unit")))
           for r in sweep if _num(r.get("unit"))]
    if not pts:
        fe = _final(summary).get("totals") or {}
        unit = _num(fe.get("unit"))
        if not unit:
            return []
        pts = [(max(1, int(facts["qty"] or 1)), _num(fe.get("material")) or 0.0,
                _num(fe.get("labour")) or 0.0, unit, None)]
    pts.sort(key=lambda t: t[0])
    try:
        from quantity_sweep import basis_from_rows                   # noqa: WPS433
    except Exception:                                                # noqa: BLE001
        basis_from_rows = None
    charges = {int(_num(r["quantity"])): _num(r.get("order_charges_per_unit"))
               for r in sweep if _num(r.get("quantity"))}
    out = []
    for q, mat, lab, unit, setup_u in pts:
        if setup_u is None and basis_from_rows is not None:
            setup_u = _num(basis_from_rows(_final(summary), q).get("setup_per_unit"))
        setup_u = min(lab, max(0.0, setup_u or 0.0))
        run_u = max(0.0, lab - setup_u)
        over = max(0.0, unit - mat - lab)
        ch = charges.get(q)
        out.append({"quantity": q, "material": mat * markup, "setup": setup_u * markup,
                    "running": run_u * markup, "overheads": over * markup,
                    "unit": unit * markup, "order": unit * markup * q,
                    "order_charges": None if ch is None else ch * markup})
    return out


def _bars_svg(model: List[Dict[str, Any]]) -> str:
    """Horizontal stacked bars, one per quantity — inline SVG, no script."""
    if not model:
        return ""
    keys = [("material", "Material, packaging & delivery", "#2a78d6"),
            ("setup", "Set-up, shared over the order", "#eb6834"),
            ("running", "Running work", "#1baf7a"),
            ("overheads", "Overheads & terms", "#eda100")]
    top = max(m["unit"] for m in model) or 1.0
    W, label_w, bar_h, gap = 640, 74, 26, 12
    H = len(model) * (bar_h + gap) + 6
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" '
             f'aria-label="Unit price at each quantity, by what it is made of">']
    for i, m in enumerate(model):
        y = i * (bar_h + gap) + 4
        parts.append(f'<text x="0" y="{y + bar_h * 0.68:.1f}" font-size="12" fill="#1f2321" '
                     f'font-weight="700">{_esc(_g(m["quantity"]))} off</text>')
        x = label_w
        span = W - label_w - 92
        for k, _, col in keys:
            w = span * (m[k] / top) if top else 0
            if w > 0.4:
                parts.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{bar_h}" '
                             f'fill="{col}"><title>{_esc(_gbp(m[k]))}</title></rect>')
            x += w
        parts.append(f'<text x="{x + 6:.1f}" y="{y + bar_h * 0.68:.1f}" font-size="12" '
                     f'fill="#1f2321" font-weight="700">{_esc(_gbp(m["unit"]))}</text>')
    parts.append("</svg>")
    legend = "".join(f'<span><i style="background:{c}"></i>{_esc(lbl)}</span>'
                     for _, lbl, c in keys)
    return "".join(parts) + f'<div class="qs-legend">{legend}</div>'


# ── THE PAGES ─────────────────────────────────────────────────────────────────────────

STORY_CSS = """
  .qs .qs-eyebrow { font-size:10px; letter-spacing:.2em; text-transform:uppercase; color:#B8860B;
                    font-weight:700; margin:0 0 6px; }
  .qs h2 { font-size:24px; line-height:1.1; margin:0 0 6px; color:#282928; letter-spacing:-.01em; }
  .qs .qs-sub { color:#5f6460; font-size:13px; margin:0 0 14px; }
  .qs .qs-dark { background:#1b1e1c; color:#eceee9; padding:24px 40px 26px; }
  .qs .qs-dark h2 { color:#fff; }
  .qs .qs-dark .qs-eyebrow { color:#F5D947; }
  .qs .qs-io { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:12px; }
  .qs .qs-io > div { border-radius:8px; padding:11px 13px; }
  .qs .qs-in { background:#262a27; border:1px solid #3a3f3b; }
  .qs .qs-out { background:#F5D947; color:#282928; }
  .qs .qs-lbl { font-size:9.5px; letter-spacing:.2em; text-transform:uppercase; font-weight:700; opacity:.8; }
  .qs .qs-io ul { list-style:none; margin:6px 0 0; padding:0; display:grid;
                  grid-template-columns:1fr 1fr; gap:4px 10px; }
  .qs .qs-io li { font-size:12px; line-height:1.25; }
  .qs .qs-io li b { font-size:18px; display:block; line-height:1.05; }
  .qs .qs-in li b { color:#fff; }
  .qs .qs-chain { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:14px; }
  .qs .qs-chain > div { background:#262a27; border:1px solid #3a3f3b; border-top:3px solid #F5D947;
                        border-radius:8px; padding:10px 11px 12px; }
  .qs .qs-k { font-size:9.5px; letter-spacing:.22em; font-weight:700; color:#F5D947; }
  .qs .qs-chain h3 { font-size:14px; margin:4px 0 6px; color:#fff; }
  .qs .qs-chain p { font-size:11.5px; line-height:1.38; color:#cfd3cd; margin:0; }
  .qs .qs-chain q { display:block; font-style:italic; color:#fff; margin-bottom:5px; font-size:11.5px; }
  .qs .qs-chain q::before, .qs .qs-chain q::after { content:none; }
  .qs .qs-body { padding:22px 40px 10px; }
  .qs .qs-ev { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .qs .qs-card { border:1px solid #e3e4e0; border-radius:9px; overflow:hidden; background:#fff;
                 display:flex; flex-direction:column; break-inside:avoid; }
  .qs .qs-shot { background:#d9d9d5; border-bottom:1px solid #e3e4e0; height:150px; display:flex;
                 align-items:center; justify-content:center; overflow:hidden; }
  .qs .qs-shot img { max-width:100%; max-height:100%; display:block; }
  .qs .qs-cbody { padding:10px 12px 12px; flex:1; display:flex; flex-direction:column; gap:7px; }
  .qs .qs-ct { font-size:13px; font-weight:700; color:#282928; margin:0; }
  .qs .qs-saw { font-size:12px; line-height:1.36; color:#1c2d6b; background:#eef1f9;
                border-left:3px solid #1c2d6b; padding:6px 9px; border-radius:0 5px 5px 0; }
  .qs .qs-saw b, .qs .qs-then b { display:block; font-size:9px; letter-spacing:.18em;
                                  text-transform:uppercase; margin-bottom:2px; }
  .qs .qs-then { font-size:12px; line-height:1.4; color:#2f3430; }
  .qs .qs-then b { color:#B8860B; }
  .qs .qs-bill { margin-top:auto; font-size:11.5px; color:#282928; background:#fff6cf;
                 border-radius:5px; padding:5px 9px; line-height:1.32; }
  .qs .qs-bill b { font-size:9px; letter-spacing:.16em; text-transform:uppercase; margin-right:6px; }
  .qs .qs-trace { display:flex; gap:6px; align-items:stretch; margin:10px 0 6px; flex-wrap:wrap; }
  .qs .qs-trace > div { flex:1 1 110px; border:1px solid #e3e4e0; border-radius:7px; padding:8px 9px;
                        background:#fbfbf8; min-width:0; }
  .qs .qs-trace > div.from { background:#eef1f9; border-color:#c9d1ea; }
  .qs .qs-trace .t { font-size:9px; letter-spacing:.16em; text-transform:uppercase; color:#8a8e8a;
                     font-weight:700; }
  .qs .qs-trace .v { font-size:14px; font-weight:700; color:#282928; line-height:1.15; margin-top:2px; }
  .qs .qs-trace .n { font-size:11px; color:#5f6460; line-height:1.3; margin-top:2px; }
  .qs .qs-sum { font-size:12.5px; background:#282928; color:#fff; border-radius:7px; padding:9px 12px;
                margin:6px 0 16px; }
  .qs .qs-sum b { color:#F5D947; }
  .qs .qs-legend { display:flex; flex-wrap:wrap; gap:6px 16px; font-size:11px; color:#5f6460;
                   margin:4px 0 10px; }
  .qs .qs-legend i { display:inline-block; width:10px; height:10px; border-radius:2px;
                     margin-right:5px; vertical-align:-1px; }
  .qs table.qs-tab { width:100%; border-collapse:collapse; font-size:12.5px; margin:4px 0 12px; }
  .qs table.qs-tab th, .qs table.qs-tab td { padding:5px 6px; border-bottom:1px solid #e6e7e4;
                                             text-align:right; }
  .qs table.qs-tab th:first-child, .qs table.qs-tab td:first-child { text-align:left; }
  .qs table.qs-tab tr.tot td { font-weight:700; border-top:2px solid #282928; }
  .qs .qs-note { font-size:12px; color:#5f6460; line-height:1.45; margin:0 0 10px; }
  .qs .qs-pn { display:flex; justify-content:space-between; padding:10px 40px 18px; color:#8a8e8a;
               font-size:11px; border-top:1px solid #e6e7e4; }
  @media (max-width:640px) {
    .qs .qs-io, .qs .qs-chain, .qs .qs-ev { grid-template-columns:1fr; }
    .qs .qs-dark, .qs .qs-body { padding-left:16px; padding-right:16px; }
  }
  @media print { .qs.sheet { break-before:page; page-break-before:always; } }
"""


def _named(customer: Any) -> bool:
    """A customer the run could name — not the quotation's generic fallback."""
    return str(customer or "").strip().lower() not in ("", "customer")


def _head(sdi_logo: str, cust_header: str, middle: str) -> str:
    return (f'<div class="head"><div class="sdi">{sdi_logo}</div>'
            f'<div class="mark"><span class="eyebrow">SDI Intelligence</span>'
            f'<span class="name">{_esc(middle)}</span></div>'
            f'<div class="cust">{cust_header}</div></div>')


def reading_page(summary: Dict[str, Any], facts: Dict[str, Any], *, customer: str,
                 product: str, job_number: str, unit_price: Optional[float], qty: int,
                 sdi_logo: str, cust_header: str, page_no: str) -> str:
    cfg = _cfg()
    pack_kind = ("illustrated brief" if facts["concept"] else "drawing pack")
    given = [(facts["page_count"], "page read", "pages read"),
             (facts["documents"], "document", "documents"),
             (facts["bom_rows"] or (len(facts["made"]) + len(facts["bought"])
                                    if facts["concept"] else 0),
              *(("parts-list row", "parts-list rows") if facts["bom_rows"]
                else ("part identified", "parts identified"))),
             (facts["dxf"] + facts["models"], "flat pattern or 3D model",
              "flat patterns or 3D models")]
    produced = [(facts["lines"], "line on a costed bill", "lines on a costed bill"),
                (len(facts["departments"]), "SDI department", "SDI departments"),
                (facts["decisions"] or len(facts["labour"]),
                 *(("routing decision", "routing decisions") if facts["decisions"]
                   else ("costed work row", "costed work rows"))),
                (len(facts["sweep"]) or 1, "order quantity priced", "order quantities priced")]
    li = lambda xs: "".join(  # noqa: E731
        f"<li><b>{_esc(_g(v))}</b>{_esc(one if _num(v) == 1 else many)}</li>"
        for v, one, many in xs)
    ev = evidence_items(summary, facts)
    first_quote = next((f"“{e['saw']['text']}”" for e in ev if e.get("saw")), "")
    chain_route = " → ".join(facts["departments"][:9]) or "Made and assembled at SDI"
    built = "; ".join((f"{m} " + ", ".join(g for g, _ in gs if g)).strip()
                      for m, gs in _by_material(facts["made"])[:2])
    tp = trace_part(summary, facts) if facts.get("agree") else None
    costed = (f"{_nice(tp['description']) or tp['code']}: {_g(tp['per_sheet'])} to a sheet · "
              if tp else "") + (
        f"{_gbp(unit_price)} a unit at {_g(qty)} off" if unit_price else "priced in SDI's workbook")
    chain = [
        ("01 · READ", "Read words and pictures together",
         first_quote, f"{_g(facts['page_count'])} pages of your {pack_kind} read as one piece "
                      f"of evidence."),
        ("02 · CONCLUDED", "Decided how it is built",
         built,
         f"Materials, gauges and joints — {len(facts['made'])} parts SDI makes, "
         f"{len(facts['bought'])} bought in."),
        ("03 · CONNECTED", "Turned the design into a route", chain_route,
         "Every made part given a blank, a gauge and a path through SDI's departments."),
        ("04 · COSTED", "Priced it in SDI's workbook", costed,
         "Nested sheets, departmental rates and every line sourced."),
    ]
    chain_html = "".join(
        f'<div><div class="qs-k">{_esc(k)}</div><h3>{_esc(h)}</h3>'
        + (f"<q>{_esc(qt)}</q>" if qt else "") + f"<p>{_esc(p)}</p></div>"
        for k, h, qt, p in chain)
    # WHOSE WORDS. A brief is the customer's own document; a drawing pack is often drawn by
    # SDI for the customer, so its lines are attributed to the drawings, not to a person.
    said_by = customer if facts["concept"] and _named(customer) else (
        "Your brief" if facts["concept"] else "Your drawings")
    for_whom = customer if _named(customer) else "you"
    cards = []
    zoom = float(cfg.get("thumbnail_zoom") or 0.55)
    for e in ev:
        saw = e.get("saw")
        shot = ""
        if saw and cfg.get("page_thumbnails"):
            uri = _page_image(saw.get("path") or "", int(saw.get("page") or 1), zoom)
            if uri:
                shot = f'<div class="qs-shot"><img src="{uri}" alt="{_esc(saw.get("doc"))}, page {_esc(saw.get("page"))}"></div>'
        saw_html = (f'<div class="qs-saw"><b>{_esc(said_by)} · page {_esc(saw["page"])}</b>'
                    f'“{_esc(saw["text"])}”</div>') if saw else ""
        cards.append(f'<div class="qs-card">{shot}<div class="qs-cbody">'
                     f'<p class="qs-ct">{_esc(e["title"])}</p>{saw_html}'
                     f'<div class="qs-then"><b>We concluded</b>{_esc(e["concluded"])}</div>'
                     f'<div class="qs-bill"><b>On the bill</b>{_esc(e["bill"])}</div>'
                     f'</div></div>')
    return f"""
  <div class="sheet qs">
    {_head(sdi_logo, cust_header, f"SDI to {customer} · {job_number}")}
    <div class="qs-dark">
      <div class="qs-eyebrow">{_esc(customer)} · {_esc(product)} · How we read your enquiry</div>
      <h2>We read your {_esc(pack_kind)} the way an engineer would.</h2>
      <p style="margin:0;color:#d9dcd6;font-size:13.5px;line-height:1.45">SDI Intelligence worked
      out what the product is made of, how SDI would make each part and what it costs — and
      kept its working, so every line on the price can be traced back to your own pages.</p>
      <div class="qs-io">
        <div class="qs-in"><div class="qs-lbl">What we were given</div><ul>{li(given)}</ul></div>
        <div class="qs-out"><div class="qs-lbl">What we produced</div><ul>{li(produced)}</ul></div>
      </div>
      <div class="qs-chain">{chain_html}</div>
    </div>
    <div class="qs-body">
      <div class="qs-eyebrow">What we read · what we concluded</div>
      <h2>Your words in, decisions out</h2>
      <p class="qs-sub">Blue boxes quote your pages word for word; beneath each is what we
      concluded, and where it landed on the costed bill.</p>
      <div class="qs-ev">{''.join(cards)}</div>
    </div>
    <div class="qs-pn"><span>we.are.sdi · wearesdi.com</span>
      <span>Your pages are reproduced for {_esc(for_whom)} only · {_esc(page_no)}</span></div>
  </div>"""


def figures_agree(summary: Dict[str, Any], facts: Dict[str, Any],
                  unit_price: Optional[float], markup: float) -> bool:
    """ONE DOCUMENT, ONE PRICE. The workbook rows and the quantity sweep on the record must
    give the figure the price page shows, or this page shows none of them.

    The record is stamped when the run calculates the sheet; an estimator who amends the sheet
    and regenerates the quote can leave a sweep (and, read back later, rows) from before the
    change. A sweep whose order-quantity column disagrees is dropped and the stamped totals
    are used; stamped totals that disagree mean the rows are stale too, and nothing priced is
    drawn. A page with no price shows no breakdown of one."""
    if unit_price is None:
        return False
    tol = max(0.01, abs(unit_price) * 1e-4)
    q = int(facts.get("qty") or 0)
    at_q = [r for r in facts["sweep"] if int(_num(r.get("quantity")) or 0) == q]
    if at_q and abs((_num(at_q[0].get("unit")) or 0.0) * markup - unit_price) > tol:
        facts["sweep"] = []
    unit = _num((_final(summary).get("totals") or {}).get("unit"))
    if unit is not None and abs(unit * markup - unit_price) > tol:
        return False
    return unit is not None or bool(facts["sweep"])


def costing_page(summary: Dict[str, Any], facts: Dict[str, Any], *, customer: str,
                 product: str, job_number: str, qty: int, markup: float, basis: str,
                 sdi_logo: str, cust_header: str, page_no: str,
                 unit_price: Optional[float] = None) -> str:
    cfg = _cfg()
    agree = bool(facts.get("agree"))
    tp = trace_part(summary, facts) if agree else None
    trace_html = ""
    if tp:
        said = tp.get("said")
        cells = [("from", "From your pack", f"{_nice(tp['description']) or tp['code']} ×{_g(tp['qty'])}",
                  (f"“{said['text']}” · page {said['page']}" if said else
                   (tp["seen"] or tp["code"]))),
                 ("", "Blank", (f"{_g(tp['length'])} × {_g(tp['width'])} mm"
                                if tp["length"] and tp["width"] else "—"),
                  f"{tp['gauge']:g} mm {tp['material']}" if tp["gauge"] else tp["material"]),
                 ("", "Nest", f"{_g(tp['per_sheet'])} to a sheet", "on SDI's standard stock")]
        for s in tp["steps"][:5]:
            cells.append(("", s["op"], _gbp((s["value"] or 0) * markup) + " a unit",
                          f"the row's figure, shared with {s['shared']} other "
                          f"part{'s' if s['shared'] != 1 else ''}"
                          if s["shared"] else "this part's own row"))
        cells.append(("", "Material line", _gbp(tp["value"] * markup), f"for all {_g(tp['qty'])}"))
        trace_html = "<div class=\"qs-trace\">" + "".join(
            f'<div class="{c}"><div class="t">{_esc(t)}</div><div class="v">{_esc(v)}</div>'
            f'<div class="n">{_esc(n)}</div></div>' for c, t, v, n in cells) + "</div>"
        trace_html += (f'<div class="qs-sum">The workbook\'s own sum: <b>{_gbp(tp["sheet"])}</b> '
                       f'sheet ÷ <b>{_g(tp["per_sheet"])}</b> = <b>{_gbp(tp["each"])}</b> each × '
                       f'<b>{_g(tp["qty"])}</b> × <b>{1 + tp["scrap"]:.2f}</b> scrap = '
                       f'<b>{_gbp(tp["value"])}</b></div>')
    model = cost_model(summary, facts, markup=markup) if agree else []
    # THE ORDER QUANTITY'S COLUMN IS THE FIRST PAGE'S FIGURE, to the penny: the sweep keeps
    # pence and the price page does not round, so 200 × £461.38 would print 48p away from
    # the order value above it. Overheads take up the difference, so the column still adds.
    for m in model:
        if unit_price is not None and m["quantity"] == int(qty or 0):
            m["unit"], m["order"] = unit_price, unit_price * m["quantity"]
            m["overheads"] = max(0.0, unit_price - m["material"] - m["setup"] - m["running"])
    model_html = ""
    if model and cfg.get("show_cost_structure"):
        heads = "".join(f"<th>{_esc(_g(m['quantity']))} off</th>" for m in model)

        def _row(label: str, key: str, cls: str = "") -> str:
            return (f'<tr class="{cls}"><td>{_esc(label)}</td>'
                    + "".join(f"<td>{_esc(_gbp(m[key]))}</td>" for m in model) + "</tr>")
        lo, hi = model[0], model[-1]
        why = ""
        if len(model) >= 2 and lo["setup"] > 0:
            why = (f"At {_g(lo['quantity'])} off, {_gbp(lo['setup'])} of machine and line "
                   f"set-up rests on each unit; at {_g(hi['quantity'])} off it is "
                   f"{_gbp(hi['setup'])}, while running work holds at {_gbp(hi['running'])} "
                   f"because the work in each unit does not change.")
            if lo.get("order_charges") and hi.get("order_charges") is not None \
                    and lo["order_charges"] > hi["order_charges"]:
                why += (f" Packaging and delivery, priced for the whole order, fall from "
                        f"{_gbp(lo['order_charges'])} to {_gbp(hi['order_charges'])} a unit "
                        f"the same way.")
        model_html = (f'<div class="qs-eyebrow" style="margin-top:6px">The price at each quantity</div>'
                      f'<h2>Set-up spreads; running work stays</h2>'
                      f'<p class="qs-note">{_esc(why)}</p>'
                      + _bars_svg(model)
                      + '<table class="qs-tab"><tr><th>£ a unit, ex VAT</th>' + heads + "</tr>"
                      + _row("Material, packaging & delivery", "material")
                      + _row("Set-up, shared over the order", "setup")
                      + _row("Running work", "running")
                      + _row("Overheads & terms", "overheads")
                      + _row("Unit price", "unit", "tot")
                      + _row("Order value", "order")
                      + "</table>")
    elif model:
        heads = "".join(f"<th>{_esc(_g(m['quantity']))} off</th>" for m in model)
        model_html = ('<div class="qs-eyebrow" style="margin-top:6px">The price at each quantity</div>'
                      '<table class="qs-tab"><tr><th>£, ex VAT</th>' + heads + "</tr>"
                      + "<tr><td>Unit price</td>" + "".join(
                          f"<td>{_esc(_gbp(m['unit']))}</td>" for m in model) + "</tr>"
                      + '<tr class="tot"><td>Order value</td>' + "".join(
                          f"<td>{_esc(_gbp(m['order']))}</td>" for m in model) + "</tr></table>")
    pc = summary.get("project_costs") if isinstance(summary.get("project_costs"), dict) else {}
    # The lines the order carries — the same states the plan totals (estimator.project_costs).
    pc_lines = [l for l in (pc.get("lines") or []) if isinstance(l, dict)
                and str(l.get("state") or "charged") in ("charged", "provisional")
                and (_num(l.get("order_gbp")) or 0) > 0]
    pc_html = ""
    pc_total = sum(_num(l.get("order_gbp")) or 0 for l in pc_lines)
    if pc_lines:
        pc_html = ('<div class="qs-eyebrow" style="margin-top:6px">One-off costs for the order</div>'
                   '<p class="qs-note">Charged once for the order — not in the unit price.</p>'
                   '<table class="qs-tab"><tr><th>Item</th><th>£ for the order</th></tr>'
                   + "".join(f"<tr><td>{_esc(str(l.get('name') or l.get('code') or ''))}</td>"
                             f"<td>{_esc(_gbp(l.get('order_gbp')))}</td></tr>" for l in pc_lines)
                   + f'<tr class="tot"><td>Total</td><td>{_esc(_gbp(pc_total))}</td></tr>'
                   + (f'<tr><td>Order total at {_esc(_g(qty))} off, with these</td>'
                      f'<td>{_esc(_gbp(unit_price * int(qty) + pc_total))}</td></tr>'
                      if (agree and unit_price is not None and qty) else "")
                   + "</table>")
    intro = ('<h2>One part, followed end to end</h2><p class="qs-sub">How a line on your pages '
             'became a priced line — every line on the bill is built the same way, in SDI\'s own '
             'costing template.</p>' if tp else
             '<h2>How the price is built</h2><p class="qs-sub">Every line on the bill is costed '
             'in SDI\'s own costing template.</p>')
    made = facts["made"]
    qtys =", ".join(f"{_g(m['quantity'])}" for m in model) or _g(qty)
    basis = str(basis or "").strip()
    if basis and basis[-1] not in ".!?":
        basis += "."
    basis_html = (f'<div class="qs-eyebrow" style="margin-top:6px">Basis</div>'
                  f'<p class="qs-note">{_esc(basis)} Priced at {_esc(qtys)} off, GBP, ex VAT, '
                  f'in SDI\'s own costing workbook from {_g(facts["page_count"])} pages of your '
                  f'{"brief" if facts["concept"] else "drawings"}; {len(made)} made part'
                  f'{"s" if len(made) != 1 else ""} sized from '
                  f'{"your visuals and stated dimensions" if facts["concept"] else "your drawings"}.</p>')
    return f"""
  <div class="sheet qs">
    {_head(sdi_logo, cust_header, f"SDI to {customer} · {job_number}")}
    <div class="qs-body">
      <div class="qs-eyebrow">{_esc(product)} · From drawing to price</div>
      {intro}
      {trace_html}
      {model_html}
      {pc_html}
      {basis_html}
    </div>
    <div class="qs-pn"><span>we.are.sdi · Design-led manufacturer · Loughborough, UK</span>
      <span>{_esc(page_no)}</span></div>
  </div>"""


def story_pages(summary: Dict[str, Any], parts: List[Dict[str, Any]], *, customer: str,
                product: str, job_number: str, qty: int, unit_price: Optional[float],
                markup: float, basis: str, sdi_logo: str, cust_header: str) -> Tuple[str, str]:
    """(css, html) for the pages after the price — or ("", "") when switched off or when the
    run left nothing to tell (a run that costed nothing has no story)."""
    if not _cfg().get("story_pages"):
        return "", ""
    try:
        facts = job_facts(summary, parts or [], int(qty or 0))
    except Exception:                                                # noqa: BLE001
        return "", ""
    if not facts["lines"]:
        return "", ""
    facts["markup"] = markup
    facts["agree"] = figures_agree(summary, facts, unit_price, markup)
    pages = []
    try:
        pages.append(reading_page(summary, facts, customer=customer, product=product,
                                  job_number=job_number, unit_price=unit_price, qty=qty,
                                  sdi_logo=sdi_logo, cust_header=cust_header,
                                  page_no="02 / 03"))
    except Exception as exc:                                         # noqa: BLE001
        print(f"   [quote] the reading page was skipped ({type(exc).__name__}: {exc}).",
              flush=True)
    try:
        pages.append(costing_page(summary, facts, customer=customer, product=product,
                                  job_number=job_number, qty=qty, markup=markup, basis=basis,
                                  sdi_logo=sdi_logo, cust_header=cust_header,
                                  page_no=f"0{len(pages) + 2} / 0{len(pages) + 2}",
                                  unit_price=unit_price))
    except Exception as exc:                                         # noqa: BLE001
        print(f"   [quote] the costing page was skipped ({type(exc).__name__}: {exc}).",
              flush=True)
    if len(pages) == 2:
        pages[0] = pages[0].replace("02 / 03", "02 / 03")
    elif len(pages) == 1:
        pages[0] = pages[0].replace("02 / 03", "02 / 02")
    return STORY_CSS, "".join(pages)
